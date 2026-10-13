import sys, unittest
from unittest.mock import patch, AsyncMock
sys.path.insert(0,'tests')
suite=unittest.defaultTestLoader.loadTestsFromNames([
 'test_workbench.WorkbenchTests.test_real_docx_export_and_idempotent_persistence',
 'test_workbench.WorkbenchTests.test_risk_feedback_versions_history_ownership_and_independent_storage'])
with patch('contract_web.runtime_manager.LocalProcessDriver.health',new_callable=AsyncMock,return_value=False):
 result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
