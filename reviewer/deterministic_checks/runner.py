"""Fast, conservative naming checks for changed Java declaration lines."""
from __future__ import annotations
import re
from pathlib import Path
from reviewer.models import Finding
PASCAL=re.compile(r"^[A-Z][A-Za-z0-9]*$"); CAMEL=re.compile(r"^[a-z][A-Za-z0-9]*$"); CONSTANT=re.compile(r"^[A-Z][A-Z0-9_]*$")
def run_checks(worktree: str, evidence_dir: Path):
    diff=(evidence_dir/'pr.diff').read_text(encoding='utf-8'); changed={}; path=None
    for line in diff.splitlines():
        if line.startswith('+++ b/'): path=line[6:]; changed.setdefault(path,set())
        elif path and line.startswith('@@'):
            m=re.search(r'\+(\d+)(?:,(\d+))?',line)
            if m: changed[path].update(range(int(m.group(1)),int(m.group(1))+int(m.group(2) or 1)))
    findings=[]
    def add(file,n,name,kind,expected): findings.append(Finding(f'naming-{file}-{n}-{name}',f'{kind} name does not follow {expected}','MINOR',[{'file':file,'line':n,'symbol':name}],category='JAVA_NAMING',source='deterministic',verification_status='CONFIRMED',failure_scenario='Java convention violation',impact='Reduces consistency',recommendation=f'Rename {name} to {expected}',confidence='HIGH'))
    for rel,lines in changed.items():
        file=Path(worktree)/rel
        if not rel.endswith('.java') or not file.is_file(): continue
        for n,text in enumerate(file.read_text(encoding='utf-8',errors='replace').splitlines(),1):
            if n not in lines: continue
            m=re.search(r'\b(?:class|interface|enum|record|@interface)\s+(\w+)',text)
            if m and not PASCAL.fullmatch(m.group(1)): add(rel,n,m.group(1),'Type','PascalCase')
            m=re.search(r'\bstatic\s+final\s+[\w<>\[\]]+\s+(\w+)',text)
            if m and not CONSTANT.fullmatch(m.group(1)): add(rel,n,m.group(1),'Constant','UPPER_SNAKE_CASE')
            m=re.search(r'\b(?:public|protected|private)?\s*[\w<>\[\], ?]+\s+(\w+)\s*\(',text)
            if m and m.group(1) not in {'if','for','while','switch','catch'} and not CAMEL.fullmatch(m.group(1)): add(rel,n,m.group(1),'Method','lowerCamelCase')
    return findings, len(changed)
