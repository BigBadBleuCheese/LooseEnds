import os, py_compile, sys, zipfile
if sys.version_info[:2] != (3, 7):
    sys.exit('Build with Python 3.7: the game only loads scripts compiled by Python 3.7.')
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build', 'CodeBleu-LooseEnds.ts4script')
os.makedirs(os.path.dirname(out), exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for folder, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith('.py'):
                continue
            source = os.path.join(folder, name)
            relative = os.path.relpath(source, root)
            compiled = os.path.join(os.path.dirname(out), 'pkg', relative + 'c')
            os.makedirs(os.path.dirname(compiled), exist_ok=True)
            py_compile.compile(source, cfile=compiled, dfile=relative.replace(os.sep, '/'), doraise=True, optimize=2)
            z.write(compiled, relative.replace(os.sep, '/') + 'c')
print(out)
