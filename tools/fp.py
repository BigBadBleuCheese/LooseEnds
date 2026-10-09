"""
Reads the game's compiled scripts and prints fingerprints of their functions.

Usage: python fp.py module:Qualified.name [module:Qualified.name ...]
  e.g. python fp.py interactions.base.picker_interaction:AutonomousSimPickerSuperInteraction.has_valid_choice

The game's simulation.zip, core.zip and base.zip are found in the folder named by the LOOSE_ENDS_GAME_SCRIPTS
environment variable, otherwise in a `game` folder at the repository root, otherwise in the usual install locations.
"""

import importlib.util
import marshal
import os
import sys
import types
import zipfile

if sys.version_info[:2] != (3, 7):
    sys.exit('The game runs Python 3.7; its compiled scripts can only be read with Python 3.7.')

REPOSITORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ARCHIVES = ('simulation.zip', 'core.zip', 'base.zip')
INSTALL_LOCATIONS = (
    os.path.join(REPOSITORY, 'game'),
    r'C:\Program Files\EA Games\The Sims 4\Data\Simulation\Gameplay',
    r'C:\Program Files (x86)\Steam\steamapps\common\The Sims 4\Data\Simulation\Gameplay',
    r'C:\Program Files (x86)\Origin Games\The Sims 4\Data\Simulation\Gameplay')

_spec = importlib.util.spec_from_file_location('loose_ends_fingerprint', os.path.join(REPOSITORY, 'src', 'codebleu_loose_ends', 'fingerprint.py'))
_fingerprint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fingerprint)
fingerprint = _fingerprint.fingerprint

_modules = {}


def game_folder():
    configured = os.environ.get('LOOSE_ENDS_GAME_SCRIPTS')
    for folder in [configured] if configured else INSTALL_LOCATIONS:
        if all(os.path.isfile(os.path.join(folder, archive)) for archive in ARCHIVES):
            return folder
    raise FileNotFoundError('Could not find the game\'s {} in {}. Set LOOSE_ENDS_GAME_SCRIPTS to the folder that holds them.'.format(
        ', '.join(ARCHIVES), configured or ', '.join(INSTALL_LOCATIONS)))


def module_code(module):
    if module in _modules:
        return _modules[module]
    relative = module.replace('.', '/')
    folder = game_folder()
    for archive in ARCHIVES:
        with zipfile.ZipFile(os.path.join(folder, archive)) as scripts:
            names = set(scripts.namelist())
            for candidate in (relative + '.pyc', relative + '/__init__.pyc'):
                if candidate in names:
                    code = marshal.loads(scripts.read(candidate)[16:])
                    _modules[module] = code
                    return code
    raise KeyError(module)


def find(code, qualified_name):
    for part in qualified_name.split('.'):
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType) and constant.co_name == part:
                code = constant
                break
        else:
            raise KeyError(qualified_name)
    return code


def fp(module, qualified_name):
    code = find(module_code(module), qualified_name)
    return fingerprint(code), code.co_filename


if __name__ == '__main__':
    for argument in sys.argv[1:]:
        module, qualified_name = argument.split(':')
        value, file_name = fp(module, qualified_name)
        print('0x%016x  %s:%s  %s' % (value, module, qualified_name, file_name))
