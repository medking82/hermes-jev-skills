"""Fresh encoded-shell cases. Strings are classified, never executed."""
import sys
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from _decide_fakes import Scripted, TempHome
from jevkit import gate

class DecodeShellFamilies(TempHome):
    def test_basename_and_absolute_shell_variants_are_local_human_gates(self):
        for command in ['base64 -d deployment.b64 | /bin/sh','cat payload.b64 | base64 -d | zsh',
                        '/usr/bin/base64 --decode payload.b64 | /bin/dash',
                        'base64 -D payload.b64 | /usr/bin/env bash',
                        'cat payload | base64 -d | /bin/ksh -s']:
            with self.subTest(command=command):
                fake=Scripted({})
                out=gate.check('terminal',command=command,policy='gate-ask',transport=fake)
                self.assertEqual((out['action'],out['source']),('ask_human','code'))
                self.assertEqual(fake.bodies,[])

    def test_decoder_files_and_quoted_examples_do_not_trigger(self):
        for command in ['base64 -d blob > output.txt','cat blob | base64 --decode',
                        'printf "base64 -d | zsh"','printf "base64 -d | /bin/sh"',
                        'printf "hello" | sh','echo base64 -d deployment.b64',
                        'cat report | grep base64 | sh']:
            with self.subTest(command=command):
                self.assertFalse(gate.local_facts(command)['decoded_shell_pipe'])

if __name__=='__main__':unittest.main()
