import os,signal,subprocess,sys
from pathlib import Path
from test_governed_external_runtime import external_framework,TASK

def test_main_provider_state_adopted_after_external_result(tmp_path):
    baseline, *_ = external_framework(tmp_path/'baseline')
    expected = baseline.evolve(TASK)
    script='''import os,signal,sys
from test_governed_external_runtime import FixtureBridge, external_framework,TASK
class KillMain(FixtureBridge):
    def invoke(self,context,args,kwargs):
        value=super().invoke(context,args,kwargs)
        if context.lane=='main': os.kill(os.getpid(),signal.SIGKILL)
        return value
fw,*_=external_framework(sys.argv[1],bridge_type=KillMain)
fw.evolve(TASK)
'''
    env=os.environ.copy()
    root=Path(__file__).resolve().parents[1]
    env['PYTHONPATH']=os.pathsep.join([str(root),str(root/'tests')])
    child=subprocess.run([sys.executable,'-c',script,str(tmp_path/'run')],env=env,capture_output=True,text=True,timeout=10)
    assert child.returncode == -signal.SIGKILL, child.stderr
    resumed,*_=external_framework(tmp_path/'run',resume=True)
    result=resumed.evolve(TASK)
    assert sorted(p.artifact for p in resumed._composed.proposals.values()) == sorted(p.artifact for p in baseline._composed.proposals.values())
