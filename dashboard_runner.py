"""Run existing evidence-led auditor, the stack check and reports in a batch."""
import argparse
import subprocess
import sys
from pathlib import Path
from dashboard_core import export_merged

ROOT=Path(__file__).resolve().parent


def commands(run_dir,mode):
    inputs=Path(run_dir)/'prospects.csv'
    context=Path(run_dir)/'prospect_context.csv'
    out=Path(run_dir)/'results'
    out.mkdir(parents=True,exist_ok=True)
    cmd=[('Identify visible technology', [sys.executable,str(ROOT/'tech_stack.py'),'--input',str(inputs),'--out',str(out/'tech_stack.json'),'--max-sites','30'])]
    if mode=='full':
        cmd.extend([
            ('Audit Search & Merch', [sys.executable,str(ROOT/'auditor.py'),'--input',str(inputs),'--out',str(out),'--max-sites','30']),
            ('Create opportunity board',[sys.executable,str(ROOT/'prospect_dashboard.py'),'--input',str(out/'evidence.json'),'--out',str(out)]),
            ('Create sales shortlist',[sys.executable,str(ROOT/'commercial_outreach.py'),'--input',str(out/'evidence.json'),'--context',str(context),'--out',str(out)])
        ])
    cmd.append(('Build business-by-business profiles',
                [sys.executable,str(ROOT/'account_profiles.py'),'--run-dir',str(run_dir)]))
    return cmd


def run_batch(run_dir,mode='quick',callback=print):
    run_dir=Path(run_dir)
    if mode not in ('quick','full'):
        raise ValueError('mode must be quick or full')
    for label,args in commands(run_dir,mode):
        callback('▶ '+label)
        with subprocess.Popen(args, cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,bufsize=1) as process:
            for line in process.stdout:
                callback(line.rstrip()[:250])
            status=process.wait()
        if status:
            raise RuntimeError(f'{label} did not finish (exit code {status}); see scan messages')
    path=export_merged(run_dir)
    callback('✓ Finished: '+str(path))
    return path

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',required=True)
    parser.add_argument('--mode',choices=['quick','full'],default='quick')
    opts=parser.parse_args()
    run_batch(opts.run_dir,opts.mode)
