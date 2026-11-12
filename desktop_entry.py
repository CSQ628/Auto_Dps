import argparse
import sys
from pathlib import Path
import ctypes
import json
import threading
import urllib.request
import webbrowser
import psutil
from dps_assistant.engine import Engine
from dps_assistant.server import Server
from dps_assistant.loopback import loopback_opener
_http=loopback_opener()

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=17860);p.add_argument('--no-browser',action='store_true');p.add_argument('--stop',action='store_true');p.add_argument('--self-test-report',type=Path);args=p.parse_args()
    if args.self_test_report:
        from dps_assistant.platform_paths import RESOURCE_ROOT,VERSION,find_game,bridge_command
        import frida
        required=['assets/dps-assistant.ico','version.json','web/dist/index.html','web/dist/appreciation-code.webp','web/dist/appreciation-original.jpg',*[f'bridge/{n}.js' for n in ['il2cpp','worker','systems','planner','automation']]]
        report={'version':VERSION,'frozen':getattr(sys,'frozen',False),'frida':frida.__version__,'psutil':psutil.__version__,'game':str(find_game()),'bridge_command':bridge_command(),'resources':{name:(RESOURCE_ROOT/name).is_file() for name in required}}
        report['ok']=all(report['resources'].values());args.self_test_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return
    if args.stop:
        origin=f'http://127.0.0.1:{args.port}';state=json.load(_http.open(origin+'/api/state',timeout=5))
        req=urllib.request.Request(origin+'/api/shutdown',data=b'{}',headers={'Origin':origin,'X-CSRF-Token':state['csrf'],'Content-Type':'application/json'})
        reply=json.load(_http.open(req,timeout=5))
        if reply.get('pid'):
            try:
                previous=psutil.Process(reply['pid'])
                if abs(previous.create_time()-reply['created'])<.01:previous.wait(timeout=30)
            except psutil.NoSuchProcess:pass
        print(json.dumps(reply,ensure_ascii=False));return
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,True,'Local\\DPSAssistantMain')
    if ctypes.get_last_error()==183:
        from dps_assistant.updates import existing_instance_notice
        from dps_assistant.platform_paths import VERSION
        try:
            previous=json.load(_http.open(f'http://127.0.0.1:{args.port}/api/state',timeout=3))
            notice=existing_instance_notice(VERSION,previous.get('version'))
            if notice:ctypes.windll.user32.MessageBoxW(None,notice,'请退出旧版本助手',64)
        except Exception:pass
        if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{args.port}')
        print('助手已在运行',flush=True);return
    engine=Engine(start=False);server=Server(engine,args.port);engine.thread.start()
    from dps_assistant.tray import SystemTray
    from dps_assistant.platform_paths import RESOURCE_ROOT
    tray=SystemTray(engine,server,RESOURCE_ROOT/'assets/dps-assistant.ico');tray.start()
    from dps_assistant.updates import VersionChecker
    engine.updater=VersionChecker();engine.updater.start()
    if not args.no_browser:threading.Timer(1,lambda:webbrowser.open(server.origin)).start()
    print('DPS 自动远征 '+server.origin,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:engine.updater.stop();tray.stop();server.server_close();engine.stop()

if __name__=='__main__':
    if '--bridge-host' in sys.argv:
        sys.argv.remove('--bridge-host')
        from tools import bridge_host
    else:
        try:main()
        except Exception as error:
            from dps_assistant.storage import DATA
            import traceback
            (DATA/'startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            if getattr(sys,'frozen',False):ctypes.windll.user32.MessageBoxW(None,'助手启动失败，详细日志：'+str(DATA/'startup-error.log')+'\n'+str(error),'DPS 远征助手',16)
            else:raise
