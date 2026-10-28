"""
Imports the whole mod where none of the game modules it patches exist (as if a game update had moved everything):
every fix must stay off, the game's own code must still run, and the player is told once on entering Live mode.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]


class PackageTests(unittest.TestCase):

    def test_everything_inert_and_reported_once(self):
        sys.modules['quick_slice'] = object()
        import codebleu_loose_ends
        from codebleu_loose_ends import guard
        from sims4 import commands
        from ui import ui_dialog_notification
        from zone import Zone

        self.assertEqual(len(guard.fixes), 14)
        self.assertEqual({fix.state for fix in guard.fixes}, {guard.GAME_CHANGED})
        self.assertIn('looseends.status', commands.registered)
        self.assertIn('looseends.profile', commands.registered)
        self.assertIn('looseends.anatomy', commands.registered)
        self.assertIn('looseends.profile_autonomy', commands.registered)
        self.assertIn('looseends.watch_lag', commands.registered)
        self.assertIn('looseends.count_participants', commands.registered)
        self.assertIn('looseends.profile_next_picker', commands.registered)
        self.assertIn('looseends.time_next_picker', commands.registered)
        self.assertIn('looseends.disable', commands.registered)
        self.assertIn('looseends.enable', commands.registered)

        zone = Zone()
        self.assertEqual(zone.on_loading_screen_animation_finished(), 'vanilla')
        self.assertEqual(len(ui_dialog_notification.shown), 1)
        title, text = ui_dialog_notification.shown[0]
        self.assertEqual(title, 'Loose Ends')
        for fix in guard.fixes:
            self.assertIn(fix.title, text)
        self.assertIn('QuickSlice.ts4script', text)
        print('\n' + text)

        zone.on_loading_screen_animation_finished()
        self.assertEqual(len(ui_dialog_notification.shown), 1, 'shown only once per session')

        commands.registered['looseends.status']()
        self.assertEqual(len(commands.CheatOutput.lines), 24)


if __name__ == '__main__':
    unittest.main()
