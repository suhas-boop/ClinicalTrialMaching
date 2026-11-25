"""Criterion authoring, coordinator review and deterministic research screening."""
import argparse
import base64
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from author import PUBLIC_TOPICS, AuthorCommandError, build_packet, generate
from compiler import compile_draft, digest, evaluate
from review import ReviewQueue
from runtime.normalize import normalize

BASE = Path(__file__).resolve().parent


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    """Atomic replacement of one receipt, including interruptions during formatting."""
    path = Path(path)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def scope_for(criterion):
    inventory = load(BASE / "runtime/inventory.json")
    row = next((x for x in inventory["criteria"] if x["id"] == criterion), None)
    if row is None:
        raise ValueError("Unknown criterion in the four-site inventory.")
    study = row["study"]
    return {"criterion_id": criterion, "study": study,
            "protocol_sha256": inventory["studies"][study]["protocol_sha256"]}


def packet_for(args, queue):
    if getattr(args, "manifest", None):
        from intake_source import build_intake_packet
        manifest = load(args.manifest)
        if manifest.get("criterion_id") != args.criterion:
            raise ValueError("The selected criterion differs from the submitted manifest.")
        return build_intake_packet(manifest, args.protocol.read_bytes(), queue.answers(manifest))
    scope = scope_for(args.criterion)
    return build_packet(args.criterion, args.site, queue.answers(scope))


def read_response(raw, packet, from_file):
    def unique_pairs(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError("Duplicate JSON key in author response: " + key)
            record[key] = value
        return record
    def invalid_number(value):
        raise ValueError("Non-finite JSON number in author response: " + value)
    value = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_number)
    if not isinstance(value, dict):
        raise ValueError("The author must return one JSON object.")
    if "author_input_sha256" in value:
        if value["author_input_sha256"] != digest(packet):
            raise ValueError("Response belongs to another author input or reviewer-answer version.")
        return value["response"]
    if from_file and packet["answers"]:
        raise ValueError("Importing a response after feedback requires an envelope with author_input_sha256 and response.")
    return value


def compile_one(packet, draft, reference):
    compiled = compile_draft(packet, draft)
    if reference is None:
        return compiled
    if packet["criterion_id"] in load(BASE / "runtime/rules.json"):
        raise ValueError("A new-rule reference cannot override an existing reference.")
    if compiled["state"] == "VALIDATION_HOLD" and draft.get("disposition") == "EXECUTABLE":
        from extensions import compile_reviewed
        return compile_reviewed(packet, draft, reference)
    return compiled


def guard(compiled, packet, queue):
    if digest(queue.answers(packet)) != digest(packet["answers"]):
        return "REAUTHOR_REQUIRED", "A reviewer answer changed the author input. Generate a fresh draft."
    if compiled["state"] == "READY" and queue.open_for(packet):
        return "PROTOCOL_REVIEW", "A prior question on this criterion remains open."
    return compiled["state"], compiled.get("reason", "")


def run_author(args, queue):
    from gaps import GapLedger
    packet = packet_for(args, queue)
    ledger = GapLedger(args.state_dir / "review.sqlite3")
    sequence = ledger.begin(packet)
    run_id = uuid.uuid4().hex
    folder = args.state_dir / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "packet.json", packet)
    receipt = {"run_id": run_id, "criterion_id": args.criterion, "study": packet["study"],
               "protocol_sha256": packet["protocol_sha256"], "author_input_sha256": digest(packet),
               "started_at": datetime.now(timezone.utc).isoformat(), "state": "AUTHORING",
               "source": "saved_response" if args.response else "author_command"}
    if getattr(args, "parent_run_id", None):
        receipt["parent_run_id"] = args.parent_run_id
    save(folder / "run.json", receipt)
    try:
        if args.response:
            raw = args.response.read_text(encoding="utf-8")
        else:
            command = args.author_command or os.environ.get("POCKETMD_AUTHOR_COMMAND")
            if args.codex:
                command = [sys.executable, str(BASE / "author.py"), "codex"]
                if args.web:
                    command.append("--search")
                    for topic in args.web:
                        command.extend(["--topic", topic])
            if not command:
                raise ValueError("Choose --response, --codex or configure --author-command.")
            raw = generate(packet, command)
        (folder / "first-response.txt").write_text(raw, encoding="utf-8")
        draft = read_response(raw, packet, bool(args.response))
        if not isinstance(draft, dict):
            raise ValueError("Expected a structured author response.")
        reference = load(args.review) if args.review else None
        if reference is not None:
            save(folder / "independent-review.json", reference)
        compiled = compile_one(packet, draft, reference)
        questions = []
        if compiled["state"] in {"PROTOCOL_REVIEW", "PROTOCOL_AND_BINDING_REVIEW"}:
            if digest(queue.answers(packet)) == digest(packet["answers"]):
                questions = queue.register(packet, draft)
        state, reason = guard(compiled, packet, queue)
        gaps = ledger.record(packet, compiled, state, ticket=sequence)
        save(folder / "compiled.json", compiled)
        receipt.update(state=state, reason=reason, compiled_sha256=digest(compiled),
                       draft_sha256=digest(draft), reference_sha256=digest(reference),
                       new_questions=[{"id":q["id"], "question":q["question"]} for q in questions if q["is_new"]],
                       new_binding_gaps=[{"id":g["id"], "fact":g["fact"]} for g in gaps if g["is_new"]],
                       open_question_ids=[q["id"] for q in queue.open_for(packet)],
                       binding_gaps=[b["fact"] for b in compiled.get("binding_gaps", [])])
        if state == "READY":
            receipt.update(executable=compiled["executable"], queries=compiled["queries"])
        if state == "READY" and args.bundle:
            receipt["patient_result"] = screen_one(args, compiled, reference, packet, queue)
        return receipt
    except (RuntimeError, ValueError, KeyError, OSError, TypeError) as error:
        if isinstance(error, AuthorCommandError):
            (folder / "first-response.txt").write_text(error.stdout, encoding="utf-8")
            (folder / "provider-error.txt").write_text(error.stderr, encoding="utf-8")
            reason = f"Author command exited {error.returncode}. See provider-error.txt."
        else:
            reason = str(error)
        receipt.update(state="RUN_ERROR", reason=reason)
        return receipt
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(folder / "run.json", receipt)


def screen_one(args, compiled, reference, packet, queue):
    state, reason = guard(compiled, packet, queue)
    if state != "READY":
        return {"state": state, "reason": reason, "patient_outcome": None}
    if packet["study"] == "NCT05653388" and not args.episode:
        return {"state":"PATIENT_INPUT_ERROR","reason":"Supply the indexed cancer Condition ID with --episode.","patient_outcome":None}
    if packet["study"] != "NCT05653388" and not args.encounter:
        return {"state":"PATIENT_INPUT_ERROR","reason":"Supply the screening encounter ID with --encounter.","patient_outcome":None}
    try:
        normalized, audit = normalize(load(args.bundle))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {"state":"PATIENT_INPUT_ERROR", "reason":str(error), "patient_outcome":None}
    if reference is not None:
        from extensions import evaluate_reviewed
        timezone_name = args.timezone
        if args.onboarding:
            from onboarding import validate
            profile = validate(load(args.onboarding), packet["study"])
            timezone_name = timezone_name or profile["timezone"]
        result = evaluate_reviewed(compiled, normalized, args.patient, args.encounter, args.as_of, timezone_name=timezone_name)
    else:
        profile = load(args.onboarding) if args.onboarding else None
        options = {"timezone_name":args.timezone, "onboarding":profile}
        if packet["study"] == "NCT05653388":
            options["episode"] = args.episode
        result = evaluate(compiled, normalized, args.patient, args.encounter, args.as_of, **options)
    state, reason = guard(compiled, packet, queue)
    if state != "READY":
        return {"state":state, "reason":reason, "patient_outcome":None}
    patient_states = {"MET", "NOT_MET", "MISSING_DATA", "INVESTIGATOR_ACTIONS", "PATIENT_SURVEY"}
    return {**result, "patient_outcome":result["state"] if result["state"] in patient_states else None,
            "normalization":audit}


def replay_screen(args, queue):
    run_id = uuid.UUID(args.run_id).hex
    folder = args.state_dir / "runs" / run_id
    receipt = load(folder / "run.json")
    if "compiled_sha256" not in receipt or receipt["state"] == "RUN_ERROR":
        raise ValueError("This run did not finish compilation.")
    packet = load(folder / "packet.json")
    if receipt["author_input_sha256"] != digest(packet):
        raise ValueError("Saved author input changed.")
    raw = (folder / "first-response.txt").read_text(encoding="utf-8")
    draft = read_response(raw, packet, receipt["source"] == "saved_response")
    review_path = folder / "independent-review.json"
    reference = load(review_path) if review_path.exists() else None
    if digest(reference) != receipt["reference_sha256"] or digest(draft) != receipt["draft_sha256"]:
        raise ValueError("Saved author response or reference changed.")
    compiled = compile_one(packet, draft, reference)
    if digest(compiled) != receipt["compiled_sha256"]:
        raise ValueError("Compilation changed. Start a new run.")
    return screen_one(args, compiled, reference, packet, queue)


def resume(args, queue):
    """Rebuild from the original signed document and the current answer set."""
    run_id = uuid.UUID(args.run_id).hex
    folder = args.state_dir / "runs" / run_id
    receipt, previous = load(folder / "run.json"), load(folder / "packet.json")
    if receipt["author_input_sha256"] != digest(previous):
        raise ValueError("Saved packet did not match its run receipt.")
    args.criterion = previous["criterion_id"]
    args.parent_run_id = run_id
    attachment = previous["protocol_attachment"]["data_base64"]
    # The member name comes from the sealed inventory. The new packet builder also verifies its bytes.
    with tempfile.TemporaryDirectory() as working:
        original = base64.b64decode(attachment, validate=True)
        if previous.get("source_mode") == "uploaded_pdf":
            args.protocol = Path(working) / "protocol.pdf"
            args.protocol.write_bytes(original)
            args.manifest = Path(working) / "intake.json"
            save(args.manifest, previous["intake_manifest"])
        else:
            member = load(BASE / "runtime/inventory.json")["studies"][previous["study"]]["protocol_member"]
            args.site = Path(working) / "protocol.zip"
            with ZipFile(args.site, "w") as site:
                site.writestr(member, original)
        return run_author(args, queue)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--state-dir", type=Path, default=Path("pocketmd-state"), help="Local review queue and run history")
    subs = cli.add_subparsers(dest="action", required=True)
    def source_options(p):
        p.add_argument("criterion")
        source = p.add_mutually_exclusive_group(required=True)
        source.add_argument("--site", type=Path, help="Original protocol site ZIP for an indexed trial")
        source.add_argument("--protocol", type=Path, help="New trial PDF, paired with --manifest")
        p.add_argument("--manifest",type=Path,help="Criterion text and source locator for a newly supplied PDF")
    def patient_options(p, required):
        p.add_argument("--bundle", type=Path, required=required)
        p.add_argument("--patient", required=required, help="FHIR Patient logical ID")
        p.add_argument("--encounter", help="FHIR screening Encounter logical ID")
        p.add_argument("--episode", help="Index cancer Condition logical ID for the Michigan protocol")
        p.add_argument("--as-of", help="Offset timestamp for a reproducible screen; defaults to run time")
        p.add_argument("--timezone", help="Site IANA time zone")
        p.add_argument("--onboarding", type=Path, help="Optional native trial onboarding profile")
    p = subs.add_parser("packet", help="Export current author input and its hash")
    source_options(p)
    p.add_argument("--out", type=Path, required=True)
    for name in ("run", "resume"):
        p = subs.add_parser(name, help="Author from a site ZIP" if name=="run" else "Re-author a saved run using current reviewer answers")
        if name == "run":
            source_options(p)
        else:
            p.add_argument("run_id")
        source = p.add_mutually_exclusive_group()
        source.add_argument("--response",type=Path,help="Replay an author response")
        source.add_argument("--author-command",help="Trusted local program reading packet JSON and writing a JSON draft")
        source.add_argument("--codex",action="store_true",help="Author with the locally configured Codex CLI")
        p.add_argument("--web",choices=PUBLIC_TOPICS,action="append",metavar="TOPIC",
                       help="Separate public terminology lookup. Repeat for drug, histology, labs, performance or response.")
        p.add_argument("--review",type=Path,help="Independent engineering reference for a new supported rule")
        p.add_argument("--events-only",action="store_true",help="Print newly opened authoring actions or run failures only")
        patient_options(p,False)
    p=subs.add_parser("screen", help="Run one saved criterion on another patient snapshot")
    p.add_argument("run_id")
    patient_options(p,True)
    subs.add_parser("questions",help="List open coordinator questions")
    subs.add_parser("actions",help="List open trial questions and engineering evidence gaps")
    p=subs.add_parser("answer",help="Record a response with its authority and source")
    p.add_argument("question_id")
    for field in ("answer","authority","date","source"):
        p.add_argument("--"+field,required=True)
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    if args.action in {"run","packet"} and bool(args.protocol) != bool(args.manifest):
        cli.error("Supply the uploaded PDF and its criterion manifest together.")
    if args.action in {"run","resume"}:
        if args.web and not args.codex:
            cli.error("--web requires --codex")
        if args.bundle and not (args.patient and (args.encounter or args.episode)) or (
                not args.bundle and (args.patient or args.encounter or args.episode)):
            cli.error("A patient screen needs --bundle, --patient and the study's --encounter or --episode.")
    try:
        queue = ReviewQueue(args.state_dir / "review.sqlite3")
        if args.action == "run":
            result = run_author(args, queue)
        elif args.action == "resume":
            result = resume(args, queue)
        elif args.action == "screen":
            result = replay_screen(args, queue)
        elif args.action == "questions":
            result = queue.pending()
        elif args.action == "actions":
            from gaps import GapLedger
            ledger = GapLedger(args.state_dir / "review.sqlite3")
            result = {"coordinator":queue.pending(), "engineering":ledger.pending()}
        elif args.action == "answer":
            result = queue.answer(args.question_id,args.answer,args.authority,args.date,args.source)
        else:
            packet = packet_for(args,queue)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            save(args.out,packet)
            result = {"packet":str(args.out),"author_input_sha256":digest(packet),"scoped_answers":len(packet["answers"])}
        if getattr(args,"events_only",False):
            if result["state"] in {"RUN_ERROR","VALIDATION_HOLD","REAUTHOR_REQUIRED"} or result.get("new_questions") or result.get("new_binding_gaps"):
                event = {k:result[k] for k in ("run_id","criterion_id","state","reason","new_questions","new_binding_gaps") if k in result}
                print(json.dumps(event,indent=2,ensure_ascii=False))
        else:
            print(json.dumps(result,indent=2,ensure_ascii=False))
        return int(isinstance(result,dict) and result.get("state")=="RUN_ERROR")
    except (RuntimeError,ValueError,TypeError,OSError,KeyError,BadZipFile) as error:
        cli.exit(2,f"PocketMD: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
