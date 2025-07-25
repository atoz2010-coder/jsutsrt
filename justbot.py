import subprocess
import sys
import time
import signal
import os

# --- 설정값 ---
# 프로젝트 루트 폴더 (이 스크립트가 있는 위치)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 실행할 메인 봇 스크립트 파일 경로
INTEGRATED_BOT_SCRIPT = os.path.join(PROJECT_ROOT, "bot.py") # bot.py는 메인 봇 스크립트

# 웹 대시보드 스크립트 파일 경로 (dashboard/app.py)
DASHBOARD_SCRIPT = os.path.join(PROJECT_ROOT, "dashboard", "app.py")

# --- 프로세스 관리 리스트 ---
running_processes = []

# --- 헬퍼 함수 ---
def launch_process(name, script_path):
    """지정된 스크립트를 새 프로세스로 실행합니다."""
    print(f"🚀 {name} 실행 중: {script_path}")
    
    # 현재 가상 환경의 Python 인터프리터 경로를 정확히 찾습니다.
    # Windows: .venv\Scripts\python.exe
    # Linux/macOS: .venv/bin/python
    python_executable = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_executable): # Windows 스크립트 경로가 아니면 Linux/macOS 경로 시도
        python_executable = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    
    # 그래도 찾지 못하면 시스템의 기본 python을 사용 (비추천)
    if not os.path.exists(python_executable):
        python_executable = sys.executable
        print(f"⚠️ 경고: 가상 환경 Python을 찾을 수 없습니다. 시스템 Python ({python_executable})을 사용합니다.")


    process = subprocess.Popen([python_executable, script_path], cwd=PROJECT_ROOT)
    running_processes.append((name, process))
    print(f"✅ {name} 시작 완료 (PID: {process.pid})")
    return process

def cleanup_processes():
    """실행 중인 모든 프로세스를 종료합니다."""
    print("\n--- 저스트봇 및 대시보드 종료 시작 ---") # "통합 RP 봇" -> "저스트봇"
    for name, process in running_processes:
        if process.poll() is None: # 프로세스가 아직 실행 중인 경우
            print(f"🔴 {name} 종료 중 (PID: {process.pid})...")
            process.terminate() # 프로세스 종료 요청
            try:
                process.wait(timeout=5) # 5초 대기
                print(f"✅ {name} 종료 완료.")
            except subprocess.TimeoutExpired:
                print(f"🔥 {name} 종료 시간 초과, 강제 종료 (PID: {process.pid})...")
                process.kill() # 강제 종료
                print(f"✅ {name} 강제 종료 완료.")
        else:
            print(f"✔️ {name} 이미 종료되었습니다.")
    print("--- 저스트봇 및 대시보드 종료 완료 ---") # "통합 RP 봇" -> "저스트봇"

# --- Ctrl+C 시그널 핸들러 ---
def signal_handler(sig, frame):
    """Ctrl+C 시그널을 처리하여 프로세스를 정리합니다."""
    print("\nCtrl+C 감지! 프로그램을 종료합니다.")
    cleanup_processes()
    sys.exit(0)

# 시그널 핸들러 등록
signal.signal(signal.SIGINT, signal_handler)

# --- 메인 실행 블록 ---
if __name__ == "__main__":
    print("--- 저스트봇 실행기 시작 ---") # "통합 RP 봇" -> "저스트봇"
    print("⚠️ 봇들이 실행되는 동안 이 터미널을 닫지 마세요.")
    print("⚠️ 봇 초기화가 진행됩니다. 잠시 기다려 주세요.")

    # 1. DB 파일 초기화 (선택 사항: 만약 기존 DB를 삭제하고 새로 시작하고 싶다면)
    # db_file_path = os.path.join(PROJECT_ROOT, "rp_server_data.db")
    # if os.path.exists(db_file_path):
    #     os.remove(db_file_path)
    #     print(f"🚫 기존 데이터베이스 파일 '{db_file_path}'을(를) 삭제했습니다.")

    # 2. 통합 봇 스크립트 실행 (모든 Cog 로드 및 DB 테이블 생성)
    # 봇 초기화 및 Cog 로드, DB 테이블 생성 시간 고려하여 충분히 대기
    launch_process("저스트봇", INTEGRATED_BOT_SCRIPT) # "통합 RP 봇" -> "저스트봇"
    time.sleep(15) # 봇이 완전히 초기화되고 Cog 로드를 마칠 시간을 줍니다.

    # 3. 웹 대시보드 스크립트 실행
    launch_process("웹 대시보드", DASHBOARD_SCRIPT)

    print("\n--- 저스트봇 및 웹 대시보드 시작 요청 완료 ---") # "통합 RP 봇" -> "저스트봇"
    print("이제 백그라운드에서 봇들이 실행될 것입니다.")
    print("종료하려면 이 터미널에서 Ctrl+C를 누르거나, '봇 스탑!'을 입력하세요.")

    try:
        while True:
            stop_command = input("명령어를 입력하세요 (종료: '봇 스탑!'): ")
            if stop_command.strip().lower() == "봇 스탑!":
                print("종료 명령어를 받았습니다.")
                break
            else:
                print("알 수 없는 명령어입니다. 다시 시도하세요.")

    except KeyboardInterrupt:
        pass
    finally:
        cleanup_processes()
        sys.exit(0)