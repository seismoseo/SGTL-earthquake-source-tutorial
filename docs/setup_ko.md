# 설치 안내: 노트북 PC에서 첫 주피터 노트북까지

아래 단계를 순서대로 따라 하세요. 단계마다 무엇을 입력하고 무엇이 보여야 하는지 적어 두었습니다. 꺾쇠괄호로 표시한
부분은 바꿔 넣을 자리입니다. `<your_id>`에는 서버 사용자 이름을, `<server>`에는 멘토가 알려 준 서버 주소를 꺾쇠괄호 없이
입력하세요. English: [setup.md](setup.md).

**준비물:** 노트북 컴퓨터, 연구실 서버 계정(사용자 이름, 첫 비밀번호, 서버 주소), 약 두 시간.

2–3주차에 파형을 눈으로 살펴보고 도달 시각을 측정할 때는 [SeisComP GUI 실습](seiscomp_gui.md)을 이어서
진행합니다. SAC **파일**은 그대로 사용하지만 SAC **프로그램**을 먼저 배울 필요는 없습니다. SeisComP 창을
노트북 PC에 띄우려면 주피터용 터널과 별도로 X 서버와 SSH X11 전달이 필요하며, 실습 안내에 순서가 나와 있습니다.

## 1. 노트북 PC에서 터미널 열기

**터미널**은 명령을 입력하는 창이고, **셸(shell)**은 그 명령을 실행하는 프로그램입니다.

- **Windows 10/11:** Windows 키를 누르고 `PowerShell`을 입력해 **Windows PowerShell**을 엽니다. `ssh -V`를 입력하고
  Enter를 누르면 `OpenSSH_for_Windows_9.5` 같은 버전이 보여야 합니다. "인식되지 않습니다"라는 메시지가 나오면
  설정 → 시스템 → 선택적 기능 → 기능 추가 → **OpenSSH 클라이언트**를 설치한 뒤 PowerShell을 다시 엽니다.
- **macOS:** Cmd+Space를 누르고 `Terminal`(터미널)을 입력한 뒤 Enter를 누릅니다. `ssh`는 이미 설치되어 있습니다.
- **Xshell 또는 PuTTY(Windows):** 이 프로그램을 써도 됩니다. Xshell: 파일 → 새로 만들기 → 호스트 = `<server>`,
  포트 22 → 연결. PuTTY: Host Name = `<your_id>@<server>`, Port 22, Connection type SSH → Open.

## 2. 서버에 처음 접속하기

```bash
ssh <your_id>@<server>
```

- 처음 접속하면 `Are you sure you want to continue connecting (yes/no)?`라고 묻습니다. 화면의 지문(fingerprint)을
  멘토가 확인해 준 경우에만 `yes`를 입력하세요.
- 비밀번호를 입력하고 Enter를 누릅니다. **입력하는 동안 화면에 아무것도 나타나지 않는 것이 정상**입니다.
- 프롬프트가 `<your_id>@...$`처럼 바뀌면 접속된 것입니다. 다음 단계에서도 이 서버 터미널을 계속 사용하세요.
  `exit`는 접속을 끝낼 때만 입력합니다. 접속이 끝난 뒤 입력하는 명령은 노트북 PC에서 실행됩니다.

## 3. 비밀번호 바꾸기

```bash
passwd
```

현재 비밀번호를 한 번, 새 비밀번호를 두 번 입력합니다. 다른 곳에서 쓰지 않는 긴 문구를 쓰세요. 비밀번호는 파일,
주피터 노트북, 커밋, AI 대화창 어디에도 적지 마세요.

## 4. GitHub 계정 만들고 2단계 인증 켜기

1. 노트북 PC에서 <https://github.com>에 가입합니다(이미 계정이 있으면 건너뜁니다).
2. **2단계 인증(2FA)**을 켭니다: 프로필 사진 → Settings → Password and authentication → Enable two-factor
   authentication. 휴대폰 인증 앱을 쓰세요.
3. 복구 코드(recovery codes)는 서버가 **아닌** 안전한 곳(비밀번호 관리 앱이나 종이)에 보관합니다.
4. GitHub 사용자 이름을 멘토에게 알려 줍니다.

## 5. 튜토리얼 내려받기

서버에서 입력합니다.

```bash
git clone https://github.com/seismoseo/SGTL-earthquake-source-tutorial.git ~/sgtl/tutorial
cd ~/sgtl/tutorial
ls
```

`README.md`, `bin`, `docs` 등이 보여야 합니다. `~`는 홈 폴더를 뜻하며, 이 과정의 모든 파일은 `~/sgtl/`
아래에 둡니다.

## 6. 과정 소프트웨어 설치하기

```bash
bin/sgtl-install            # 드라이 런(시험 실행): 할 일을 [dry-run] 표시와 함께 보여 주기만 하고 아무것도 바꾸지 않음
bin/sgtl-install --apply    # 실제로 설치함. 시간이 걸립니다(보통 10-30분)
```

먼저 드라이 런 출력을 읽어 보세요. 모든 것은 `~/sgtl/` 아래에 설치되며 관리자 권한은 필요 없습니다. 마지막에
Jupyter 커널 **SGTL (Python 3.12)**이 만들어집니다. 이 터미널에서 과정 프로그램을 찾을 수 있도록 검색 경로를
설정한 뒤 환경을 점검합니다.

```bash
export PATH="${SGTL_HOME:-$HOME/sgtl}/envs/sgtl/bin:$PATH"
bin/sgtl doctor
```

출력은 **PASS**, **WARN**, **FAIL**로 나옵니다. FAIL은 해결한 뒤 진행하세요. 이 단계에서 자료 폴더, SeisBench
가중치와 Git 훅에 관한 경고는 정상입니다. 뒤 단계에서 설치하거나 켭니다. 대체 글꼴 경고도 허용됩니다. 다른 경고는
멘토와 함께 읽으세요([troubleshooting.md](troubleshooting.md)). 기본 설치는 환경만 설치합니다. 추가 도구와 자료를
언제 준비하는지는 [모듈 시작 전 안내](how_this_tutorial_works_ko.md)를 보세요.

## 7. 서버를 GitHub 계정과 연결하기

`gh`는 GitHub 명령줄 프로그램이며 과정 환경에 들어 있습니다.

```bash
gh auth login
```

**GitHub.com** → **HTTPS** → GitHub 자격 증명으로 Git 인증: **Yes** → **Login with a web browser**를 고릅니다.
일회용 코드가 출력되면 노트북 PC의 브라우저에서 <https://github.com/login/device>를 열어 코드를 입력하고 승인합니다.
서버로 돌아와 `gh auth status`를 실행하면 로그인되었다고 나와야 합니다.

커밋에 쓸 이름을 설정합니다. 실제 이메일이 공개되지 않도록 GitHub의 비공개 no-reply 주소를 쓰세요(GitHub →
Settings → Emails에서 확인).

```bash
git config --global user.name "Your Name"
git config --global user.email "<GitHub Settings에 표시된 정확한 no-reply 주소>"
```

튜토리얼의 비공개 사본을 만드는 과정은 M00 모듈에서 합니다([git_workflow.md](git_workflow.md)).

## 8. 서버에서 JupyterLab 시작하기

```bash
bin/sgtl-lab start            # 드라이 런: 무엇을 시작할지 보여 줌
bin/sgtl-lab start --apply    # tmux 안에서 JupyterLab을 시작함. 서버 자신(127.0.0.1)에서만 접속을 받음
```

JupyterLab은 로그아웃한 뒤에도 계속 실행됩니다(터미널 세션을 유지해 주는 프로그램인 **tmux** 안에서 실행되기
때문입니다). `sgtl-lab`은 **포트 번호**, **터널 설정 방법**, 토큰이 붙은 **링크** 세 가지를 출력합니다. 토큰은
비밀번호와 같습니다. 링크를 남에게 주거나 이슈, AI 대화창에 붙여 넣지 마세요.

## 9. 노트북 PC에서 SSH 터널 열기

**SSH 터널**은 노트북 PC의 브라우저가 ssh 연결을 거쳐 서버의 JupyterLab에 접속할 수 있게 해 줍니다. `sgtl-lab`이
출력한 포트 번호를 그대로 쓰세요. 아래에서는 `<port>`로 적었습니다.

- **PowerShell 또는 macOS 터미널:** 노트북 PC에서 터미널 창을 **새로** 열고 다음을 실행합니다.
  ```bash
  ssh -N -L <port>:127.0.0.1:<port> <your_id>@<server>
  ```
  비밀번호를 입력하면 아무것도 출력되지 않고 멈춘 것처럼 보입니다. 정상입니다. 이 창이 열려 있는 동안 터널이
  유지됩니다.
- **Xshell:** 세션 속성 → 연결 → SSH → 터널링 → 추가: 유형 Local(Outgoing), 소스 호스트 `localhost`, 수신 포트
  `<port>`, 대상 호스트 `127.0.0.1`, 대상 포트 `<port>`. 그다음 다시 연결합니다.
- **PuTTY:** Open을 누르기 전에 Connection → SSH → Tunnels에서 Source port `<port>`, Destination
  `127.0.0.1:<port>`, Local을 고르고 Add를 누릅니다. 그다음 Session → Open.

이제 출력된 링크(`http://127.0.0.1:<port>/lab?token=...`)를 노트북 PC의 브라우저에 붙여 넣습니다.

## 10. 첫 주피터 노트북 열기

서버 터미널(JupyterLab 안에도 있습니다: File → New → Terminal)에서 입력합니다.

```bash
cd ~/sgtl/tutorial
bin/sgtl new M00
```

M00 주피터 노트북을 `work/M00_.../`에 한 번만 복사합니다. 설치 프로그램과 달리 드라이 런 없이 바로 실행되지만,
파일을 복사하기만 하고 이미 있는 작업은 절대 덮어쓰지 않습니다. JupyterLab 파일
탐색기에서 `work/M00_*/M00_*.ipynb`를 엽니다. 오른쪽 위의 커널 이름이 **SGTL (Python 3.12)**인지 확인하세요
(아니면 Kernel → Change Kernel). 먼저 "Parameters"라고 적힌 첫 **코드** 셀을, 그다음
`import sgtl_tutorial as st`로 시작하는 setup 코드 셀을 Shift+Enter로 실행합니다. setup 셀이 환경과 서버 사용
한도를 짧게 보고합니다. 제목과 안내문은 텍스트 셀이므로 코드 셀 수에 넣지 않습니다. 그다음 노트북을 차례대로 읽습니다.

## SGTL 커널

**커널**은 주피터 노트북의 셀을 실행하는 프로그램입니다. SGTL 커널은 과정 환경을 쓰므로 모두가 같은 버전의 Python과
패키지를 씁니다. 이 환경에 패키지를 설치하지 마세요(`pip install` 금지). 필요한 것이 없으면 멘토에게 물어보세요.
커널 목록에 SGTL 커널이 없으면 `bin/sgtl doctor`를 실행하세요.

## 매일 할 일

1. 서버에 접속합니다(2단계). 새 서버 터미널마다 `cd ~/sgtl/tutorial`과 6단계의 `export PATH=...` 명령을
   실행한 뒤 터널을 엽니다(9단계).
2. 링크가 열리지 않으면 `bin/sgtl-lab status`로 상태를 확인한 뒤 `bin/sgtl-lab start --apply`로 JupyterLab을
   다시 시작합니다.
3. 하루에 한 번 이상 작업을 커밋합니다([git_workflow.md](git_workflow.md)).

다음 읽을거리: [how_this_tutorial_works_ko.md](how_this_tutorial_works_ko.md), [server_manners.md](server_manners.md).
