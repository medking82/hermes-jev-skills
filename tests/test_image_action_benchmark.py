"""Offline safety and accounting gates for the opt-in image action demo."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('image_action_benchmark',ROOT/'scripts/benchmark_image_actions.py')
assert spec is not None and spec.loader is not None
bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)

class ImageActionBenchmark(unittest.TestCase):
 def test_unknown_action_never_dispatches(self):
  self.assertIsNone(bench.safe_pick('invented-command',1,{'safe':{'kind':'click'}}))
 def test_low_confidence_never_dispatches(self):
  self.assertIsNone(bench.safe_pick('safe',.64,{'safe':{'kind':'click'}}))
 def test_reserved_stop_ids_never_dispatch(self):
  for key in ['reobserve','abstain']:
   self.assertIsNone(bench.safe_pick(key,1,{key:{'kind':'click'}}))
 def test_nonfinite_confidence_never_executes(self):
  for confidence in (float('nan'),float('inf'),float('-inf')):
   self.assertIsNone(bench.safe_pick('a',confidence,{'a':{}}))
 def test_exact_prevalidated_payload_retained(self):
  payload={'kind':'type','target':'Mission note','text':'LAUNCH READY'}
  self.assertIs(bench.safe_pick('safe',.65,{'safe':payload}),payload)
 def test_accounting_keeps_fallback_cost_and_excludes_visual_extra(self):
  rows=[{'route':'elements','task':'type','decision_ms':100,'verified':True,'model':'same'},
        {'route':'image','task':'type','decision_ms':180,'verified':True,'model':'same','fallback_used':True,'hybrid_decision_ms':260},
        {'route':'image','task':'visual','decision_ms':9000,'verified':True,'model':'same'}]
  report=bench.summarize(rows)
  self.assertEqual(report['image']['decisions'],1)
  self.assertEqual(report['image']['fallbacks'],1)
  self.assertEqual(report['image']['median_decision_ms'],180)
  self.assertEqual(report['image']['median_with_fallback_ms'],260)
 def test_driver_error_is_not_success(self):
  with self.assertRaises(RuntimeError):bench.unwrap({'result':{'isError':True}})

if __name__=='__main__':unittest.main()
