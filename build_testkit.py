import os, py_compile, sys, zipfile
if sys.version_info[:2] != (3, 7):
    sys.exit('Build with Python 3.7: the game only loads scripts compiled by Python 3.7.')
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.join(here, 'testkit')
out = os.path.join(here, 'build', 'CodeBleu-LooseEnds-TestKit.ts4script')
os.makedirs(os.path.join(here, 'build', 'testkit_pkg'), exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for folder, _, files in os.walk(root):
        for name in sorted(files):
            if name.endswith('.py'):
                source = os.path.join(folder, name)
                relative = os.path.relpath(source, root).replace(os.sep, '/')
                compiled = os.path.join(here, 'build', 'testkit_pkg', relative + 'c')
                os.makedirs(os.path.dirname(compiled), exist_ok=True)
                py_compile.compile(source, cfile=compiled, dfile=relative, doraise=True, optimize=2)
                z.write(compiled, relative + 'c')
print(out)
