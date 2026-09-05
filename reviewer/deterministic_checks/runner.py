"""Fast, conservative naming checks for changed Java declaration lines."""
from __future__ import annotations
import re
from pathlib import Path
from reviewer.models import Finding
PASCAL=re.compile(r"^[A-Z][A-Za-z0-9]*$"); CAMEL=re.compile(r"^[a-z][A-Za-z0-9]*$"); CONSTANT=re.compile(r"^[A-Z][A-Z0-9_]*$")
def run_checks(worktree: str, evidence_dir: Path):
    diff=(evidence_dir/'pr.diff').read_text(encoding='utf-8'); changed={}; path=None; new_line=0; in_hunk=False
    for line in diff.splitlines():
        if line.startswith('+++ b/'): path=line[6:]; changed.setdefault(path,set()); in_hunk=False
        elif line.startswith('@@'):
            m=re.search(r'\+(\d+)(?:,\d+)?',line); new_line=int(m.group(1)) if m else 0; in_hunk=True
        elif in_hunk and path:
            if line.startswith('+'): changed[path].add(new_line); new_line+=1
            elif line.startswith(' '): new_line+=1
    findings=[]
    def add(file,n,name,kind,expected):
        suggestion=(name[:1].lower()+name[1:]) if expected=='lowerCamelCase' else (re.sub(r'(?<!^)([A-Z])',r'_\1',name).upper() if expected=='UPPER_SNAKE_CASE' else '')
        findings.append(Finding(f'naming-{file}-{n}-{name}',f'{kind} name does not follow {expected}','MINOR',[{'file':file,'line':n,'symbol':name}],category='JAVA_NAMING',source='deterministic',verification_status='CONFIRMED',failure_scenario='Java convention violation',impact='Reduces consistency',recommendation=f'Symbol: {name}. Expected convention: {expected}.'+(f' Suggested: {suggestion}.' if suggestion else ''),confidence='HIGH'))
    for rel,lines in changed.items():
        file=Path(worktree)/rel
        if not rel.endswith('.java') or not file.is_file(): continue
        for n,text in enumerate(file.read_text(encoding='utf-8',errors='replace').splitlines(),1):
            if n not in lines: continue
            m=re.search(r'^\s*package\s+([\w.]+)\s*;',text)
            if m and any(not p.islower() for p in m.group(1).split('.')): add(rel,n,m.group(1),'Package','lowercase')
            m=re.search(r'\b(?:class|interface|enum|record|@interface)\s+(\w+)',text)
            if m and not PASCAL.fullmatch(m.group(1)): add(rel,n,m.group(1),'Type','PascalCase')
            m=re.search(r'\bstatic\s+final\s+[\w<>\[\]]+\s+(\w+)',text)
            if m and not CONSTANT.fullmatch(m.group(1)): add(rel,n,m.group(1),'Constant','UPPER_SNAKE_CASE')
            m=re.search(r'^\s*(?:public|protected|private)?\s*[\w<>\[\], ?]+\s+(\w+)\s*\(([^)]*)\)',text)
            if m and m.group(1) != Path(rel).stem:
                if not CAMEL.fullmatch(m.group(1)): add(rel,n,m.group(1),'Method','lowerCamelCase')
                for param in m.group(2).split(','):
                    words=param.strip().split()
                    if len(words)>1 and not CAMEL.fullmatch(words[-1]): add(rel,n,words[-1],'Parameter','lowerCamelCase')
            m=re.search(r'^\s*(?:private|protected|public)\s+(?!static\s+final)[\w<>\[\], ?]+\s+(\w+)\s*(?:=|;)',text)
            if m and not CAMEL.fullmatch(m.group(1)): add(rel,n,m.group(1),'Field','lowerCamelCase')
    return findings, sum(1 for p in changed if p.endswith('.java') and (Path(worktree)/p).is_file())
