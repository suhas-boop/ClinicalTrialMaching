"""PocketMD research pipeline entry points. Run with --help to see supported commands."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
COMMANDS={
    'vignette':'criterion_workbench/screen_vignette.py',
    'vignette-case':'criterion_workbench/review_vignette_case.py',
    'registry-context':'criterion_workbench/registry_context.py',
    'retest':'nih_benchmark/round3/predict.py',
    'demo':'criterion_workbench/demo_rule_loop.py',
    'author':'criterion_workbench/rules.py',
    'screen':'criterion_workbench/review_study.py',
    'studies':'eight_rules/release/screen_study.py',
    'review':'criterion_workbench/evidence_review.py',
    'recover':'criterion_workbench/recover_records.py',
    'trialgpt-screen':'nih_benchmark/round8/screen_release.py',
    'audit-abstentions':'nih_benchmark/round13/audit.py',
    'trial-disposition':'nih_benchmark/round17/trial_disposition.py',
    'user-clarified-score':'nih_benchmark/round21/user_clarified.py',
    'respiratory-exam-score':'nih_benchmark/round20/respiratory.py',
    'exam-evidence-score':'nih_benchmark/round19/exam_bounds.py',
    'evidence-score':'nih_benchmark/round16/evidence_score.py',
    'trialgpt-evaluate':'nih_benchmark/round14/evaluate.py',
    'fhir-prescreen':'nih_benchmark/round14/term_policy.py',
    'source-worklist':'nih_benchmark/round14/source_worklist.py',
    'fhir-query':'nih_benchmark/round9/chart.py',
    'fhir-serve':'nih_benchmark/round9/serve.py',
    'fhir-convert':'nih_benchmark/round12/intake.py',
    'fhir-replay':'nih_benchmark/round12/screen.py',
    'fhir-compile':'nih_benchmark/round11/catalog.py',
    'fhir-screen':'nih_benchmark/round12/screen.py',
    'records':'criterion_workbench/record_search.py',
    'screen-lab':'criterion_workbench/native_lab.py',
    'chart-links':'criterion_workbench/chart_links.py',
    'benchmark':'nih_benchmark/review_replay.py',
    'verify-studies':'eight_rules/release/verify_rules.py',
    'verify-medication':'michigan_course_binding/check_ingredients.py',
}
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=list(COMMANDS)+['test'])
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.command=='test':
        command=['-m','unittest','discover','-s',str(ROOT/'criterion_workbench')]
    else:
        command=[str(ROOT/COMMANDS[args.command])]
    return subprocess.call([sys.executable,'-B',*command,*args.arguments])
if __name__=='__main__':
    sys.exit(main())
