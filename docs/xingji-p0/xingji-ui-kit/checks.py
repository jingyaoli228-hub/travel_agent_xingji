import os,re,json,glob,subprocess,shutil,sys
K='/workspace/xingji-visual/kit';T='/workspace/xingji-visual/itest';shutil.rmtree(T,ignore_errors=True)
M=T+'/miniprogram';os.makedirs(M+'/pages/index');os.makedirs(M+'/assets')
for d in ['styles','components','utils']: shutil.copytree(f'{K}/{d}',f'{M}/{d}')
shutil.copytree(f'{K}/assets/markers',f'{M}/assets/markers')
json.dump({"miniprogramRoot":"miniprogram/","appid":"touristappid","compileType":"miniprogram"},open(T+'/project.config.json','w'))
names=sorted(os.listdir(K+'/components'))
json.dump({"pages":["pages/index/index"],"usingComponents":{n:f"/components/{n}/index" for n in names}},open(M+'/app.json','w'))
open(M+'/app.wxss','w').write('@import "styles/index.wxss";\n');open(M+'/app.js','w').write('App({})')
open(M+'/pages/index/index.json','w').write('{"navigationStyle":"custom"}');open(M+'/pages/index/index.wxss','w').write('')
open(M+'/pages/index/index.js','w').write("const {poiMarker}=require('../../utils/map-style.js');Page({data:{m:[poiMarker(1,39.9,116.4,1)]}})")
open(M+'/pages/index/index.wxml','w').write(''.join(f'<{n}></{n}>' for n in names)+'<map markers="{{m}}"></map>')
err=[]
def res(base,p,root): return os.path.normpath(os.path.join(root,p.lstrip('/')) if p.startswith('/') else os.path.join(os.path.dirname(base),p))
for root in (M,K):
  for j in glob.glob(root+'/**/*.json',recursive=True):
    try: d=json.load(open(j))
    except Exception as e: err.append(f'json {j} {e}');continue
    for n,p in d.get('usingComponents',{}).items():
      r=res(j,p,root)
      for ext in ('.js','.json','.wxml','.wxss'):
        if not os.path.exists(r+ext): err.append(f'{j}: {n} missing {r+ext}')
    for p in d.get('pages',[]):
      if not os.path.exists(f'{root}/{p}.wxml'): err.append('page missing '+p)
  ic=open(root+'/styles/icons.wxss').read()
  for f in glob.glob(root+'/**/*.wxss',recursive=True):
    s=open(f).read()
    for m in re.findall(r'@import\s+"([^"]+)"',s):
      if not os.path.exists(res(f,m,root)): err.append(f'{f} import {m}')
    s2=re.sub(r'url\("data:[^"]*"\)','',s)
    if re.search(r'(^|[\s,{}>+~])\*',re.sub(r'/\*.*?\*/','',s2,flags=re.S)): err.append(f'{f} uses *')
    if re.search(r'url\(|@font-face|https?:',s2): err.append(f'{f} external url')
    if re.search(r'\[[a-z-]+[=\]]',s2): err.append(f'{f} attr selector')
    if s.count('{')!=s.count('}'): err.append(f'{f} braces')
    if '/components/' in f and re.search(r'(^|\})\s*(page|view|text|image|button|#[\w-]+)\s*[{,.:]',s): err.append(f'{f} tag/id selector in component')
    if '/pages/' in f and re.search(r'(^|\})\s*xj-',s): err.append(f'{f} custom-component tag selector')
  for f in glob.glob(root+'/**/*.js',recursive=True):
    if subprocess.run(['node','--check',f]).returncode: err.append('js '+f)
    for m in re.findall(r"require\('([^']+)'\)",open(f).read()):
      if not os.path.exists(res(f,m,root)): err.append(f'{f} require {m}')
  for f in glob.glob(root+'/**/*.wxml',recursive=True):
    s=re.sub(r'<!--.*?-->','',open(f).read(),flags=re.S);st=[]
    for mm in re.finditer(r'<(/?)([a-zA-Z][\w-]*)((?:[^>"]|"[^"]*")*?)(/?)>',s):
      c,t,_,sc=mm.groups()
      if sc: continue
      if c:
        if not st or st[-1]!=t: err.append(f'wxml mismatch {f} {t}');break
        st.pop()
      else: st.append(t)
    if st: err.append(f'wxml unclosed {f} {st}')
    for m in re.findall(r'xj-icon--([a-z]+-[a-z]+)\b',s):
      if '.xj-icon--'+m+'{' not in ic: err.append(f'{f} icon {m}')
    for m in re.findall(r'xj-icon--\{\{[^}]*\}\}',s): pass
    for m in re.findall(r'/assets/markers/([\w-]+)\.png',s):
      if not os.path.exists(f'{root}/assets/markers/{m}.png'): err.append('marker '+m)
  for n in range(1,21):
    for c in('orange','navy'):
      if not os.path.exists(f'{root}/assets/markers/poi-{c}-{n}.png'): err.append(f'missing poi-{c}-{n}')
# dynamic icon names used in js/wxml ternaries
ic=open(K+'/styles/icons.wxss').read()
for f in glob.glob(K+'/**/*.*',recursive=True):
  if f.endswith(('.js','.wxml')):
    for m in re.findall(r"'([a-z]+-(?:navy|orange|grey|white|green|amber|red|blue|dark))'",open(f).read()):
      if '.xj-icon--'+m+'{' not in ic: err.append(f'{f} dyn icon {m}')
print('components:',len(names),names);print('ERRORS:',err or 'none')
