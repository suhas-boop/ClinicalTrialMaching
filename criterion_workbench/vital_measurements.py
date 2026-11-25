"""Read explicit current-patient measurement lines from the numbered vignette adapter."""
import re

READERS = {
    "heart_rate": (r"(?:heart rate|HR|pulse)", r"(?:beats/min(?:ute)?|bpm|/min)"),
    "respiratory_rate": (r"(?:respiratory rate|RR)", r"(?:breaths/min(?:ute)?|/min)"),
}
# Each segment must stand alone as a measured vital in a patient examination line.
VITAL_LINE = re.compile(r"^(?:on (?:physical )?examination,? |vital signs(?: are| include)?[: ]+)?(?:BP|blood pressure|HR|heart rate|RR|respiratory rate|pulse)\b",re.I)
CONTEXT = re.compile(r"\b(?:relative|mother|father|family|goal|target|desired|prior|previous|yesterday|baseline was|if|would|should|denies|estimated|exercise|standing|supine)\b",re.I)
PATTERNS = {key:re.compile(r"(?:"+name+r")\s*(?:is|was|of|:|=)?\s*(\d{1,3})\s*"+unit+r"\.?",re.I)
            for key,(name,unit) in READERS.items()}


def measurements(lines):
    found = {}
    for i,line in lines.items():
        if not VITAL_LINE.match(line) or CONTEXT.search(line):
            continue
        cleaned = re.sub(r"^(?:on (?:physical )?examination,? |vital signs(?: are| include)?[: ]+)","",line,flags=re.I)
        for part in re.split(r"[,;]",cleaned):
            for k,pattern in PATTERNS.items():
                match=pattern.fullmatch(part.strip())
                if match:
                    found.setdefault(k,[]).append((int(match[1]),i))
    return {k:{"value":rows[0][0],"sentences":sorted({i for _,i in rows}),"quote":lines[rows[0][1]]}
            for k,rows in found.items() if len({v for v,_ in rows})==1}
