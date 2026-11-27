# 이 튜토리얼의 진행 방식

English: [how_this_tutorial_works.md](how_this_tutorial_works.md)

과정은 M00부터 M60까지 이어지는 **모듈**로 이루어지며, 모듈 하나가 Jupyter 노트북 하나입니다. `bin/sgtl new MXX`는
모듈을 `work/MXX_slug/`에 한 번 복사하고, 작업은 이 복사본에서만 합니다. `docs/notebooks/`의 원본은 튜토리얼
소유이며 업데이트 때 바뀝니다. 순서와 미리 준비할 것은 [수업 안내](notebooks/README.md)에 있습니다.

노트북은 머리말(걸리는 시간, 먼저 끝낼 모듈, 새 용어)로 시작하고, 먼저 실행할 셀이 둘 있습니다. **parameters**
셀은 바꿔도 되는 값을 두는 유일한 곳이고, **setup** 셀의 `S = st.init("MXX")`는 서버를 공정하게 나눠 쓰도록
스레드와 메모리를 제한합니다. 그다음 각 부(Part)는 짧은 글과 코드 셀 하나로 개념을 보여 줍니다. 실행하고 결과를
보세요.

## 과제는 다섯 단계

모든 과제(`MXX-Tn`)는 같은 셀로 이루어집니다. 아래는 M05의 과제입니다.

```text
### M05-T3 · Completeness from the peak of the histogram · core · about 60 min

Write `mc_maxc(mags, dm, correction=0.2)`: the center of the bin with the most events, plus `correction`.
- Bins have width `dm` and are centered on the listed values (multiples of `dm`).
- If several bins share the largest count, take the smallest magnitude.
- `np.unique(..., return_counts=True)` counts how often each value occurs.

Example: 1.0, 1.1, 1.1, 1.2 with `dm` = 0.1 give 1.1 + 0.2 = 1.3.

Not allowed: SeismoStats or `sgtl_tutorial` inside your function.
```

```python
# Before you code: for a catalog whose detection fades slowly over a whole magnitude unit, will MAXC + 0.2 be
# above or below the magnitude where detection is really complete?
st.predict("M05-T3", """

""")
```

```python
def mc_maxc(mags, dm, correction=0.2):
    """Maximum-curvature magnitude of completeness (Wiemer and Wyss 2000) plus a correction.

    mags       : numpy array of rounded magnitudes
    dm         : float, bin width
    correction : float, added to the peak bin (0.2 after Woessner and Wiemer 2005)
    returns    : float, magnitude of completeness
    """
    # YOUR CODE HERE
    raise NotImplementedError("M05-T3: write your code here")
```

```python
st.check("M05-T3", func=mc_maxc)
```

```text
**Explain:** In the demo below, where is MAXC + 0.2 compared with 99 % detection, and what does that do to $\hat b$?
```

1. **읽기.** 과제 설명과 함수의 설명문(docstring)을 읽습니다. 설명문에 입력, 출력, 단위가 적혀 있습니다.
2. **예측.** `Before you code` 질문의 답을 `st.predict`의 따옴표 안에 적고 셀을 실행합니다. 예측이 틀려도
   괜찮습니다. 예측과 결과의 차이에서 배웁니다. 예측을 저장해야 점검이 실행됩니다.
3. **코드 작성.** `# YOUR CODE HERE` 아래의 `raise` 줄 자리에 코드를 씁니다. 함수 이름, 인수, 설명문은 그대로
   둡니다. 과제 함수 안에서는 강의 패키지(`st`, `sgtl_tutorial`)를 쓰지 않습니다. 점검이 이를 거부하며, 과제가
   허용하지 않는다고 밝힌 라이브러리도 마찬가지입니다.
4. **점검.** `st.check` 셀을 실행합니다. 이 셀은 절대 고치지 않습니다. 답을 아는 사례로 함수를 시험해 PASS를,
   또는 이유와 함께 FAIL을 출력합니다. FAIL이 나오면 `st.hint("MXX-Tn", 1)`로 실마리를 봅니다. 2단계 힌트는 점검에
   한 번, 3단계는 두 번 실패한 뒤에 열립니다. 힌트를 써도 불이익은 없습니다. `st.reroll("MXX-Tn")`은 새 연습
   자료를 뽑습니다.
5. **설명.** Explain 질문 하나에 내 말로 1-3문장으로 답합니다. 숫자는 노트북이 출력한 값만 씁니다.

PASS는 이 사례들에서 내 함수가 기준과 일치한다는 뜻일 뿐, 방법을 이해했다는 증명은 아닙니다. 이해는 설명 답과
매주 구두 점검으로 확인합니다. 관문(gate), 멘토의 평가 기준표, 구두 점검은 [교육 과정](curriculum.md#gates)에, 다른
점검 메시지는 [문제 해결](troubleshooting.md#checks)에 있습니다.

## 커널 재시작, Run All, 선택 셀

커널을 다시 시작하면(Kernel → Restart Kernel) 모든 변수가 지워집니다. parameters 셀과 setup 셀을 실행한 뒤 끝낸
셀을 순서대로 다시 실행하세요. **Kernel → Restart Kernel and Run All Cells**는 선택 셀까지 실행하므로, 선택 과제도
준비되었을 때 씁니다. 노트북끼리는 변수를 나누지 않습니다. 이전 함수를 붙여 넣으라는 셀에는 점검을 통과한 내
함수를 그 함수가 쓰는 가져오기·상수·도우미와 함께 붙여 넣고 실행합니다.

과제는 **core**(필수, 관문은 이것만 봄), **stretch**(core 다음에 더 깊이), **research**(열린 질문, 점검이 없는 것도
있음)로 나뉩니다. 탐색 도구(explorer)와 *optional* 표시가 있는 셀은 필수가 아닙니다.

## AI 기록

AI에게 오류, 공식, 개념의 설명을 들을 수는 있지만, 과제 함수, 예측, 설명 답을 AI가 대신 써서는 안 됩니다
([AI 사용 규칙](ai_policy_ko.md)). AI를 쓸 때마다 `work/ai_log/MXX.md`에 적습니다. 예측, 점검, 힌트, 다시 뽑기는
`work/.sgtl/progress.jsonl`에 기록되고, `st.progress()`가 이를 표로 보여 줍니다. 멘토는 두 기록을 모두 읽습니다.

## 저장과 제출

Ctrl+S(Mac은 Cmd+S)로 저장하고 날마다 커밋합니다([Git 작업 방식](git_workflow.md)). 핵심 과제의 점검을 모두
통과하고 설명 답과 AI 기록을 다 썼으면 서버 터미널에서 실행합니다.

```bash
bin/sgtl submit M04            # 시험 실행: 내 사본을 점검하고 계획만 보여 줌. 아무것도 실행하지 않음
bin/sgtl submit M04 --apply    # 핵심 과제를 실행하고 기록한 뒤 멘토에게 풀 리퀘스트를 엶
bin/sgtl submit M04 --include-optional    # 심화·연구 과제도 선택함. 계획을 읽은 뒤 --apply 추가
```

`--apply`는 내 노트북의 사본을 **papermill**(브라우저 없이 노트북을 실행하는 프로그램)로 처음부터 실행합니다.
코어 하나로 최대 120분 동안 실행합니다(`--timeout 분`으로 바꿀 수 있음). 끝내지 않은 선택 과제가 있어도 핵심
과제 제출은 막히지 않습니다. 선택된 점검은 이번 실행에서 모두 PASS여야 하며, 예전 PASS는 인정되지 않습니다. 내
노트북 파일은 바뀌지 않습니다. 실행된 사본, 실행 기록, `submission.json`은 `work/submissions/M04/<UTC 시각>/`에
저장됩니다. `submission.json`에는 파일의 **SHA-256 지문**(파일이 1바이트만 바뀌어도 달라지는 코드)이 들어
있습니다. 이 파일들은 내 비공개 사본의 새 브랜치 `submit/M04-<UTC 시각>`에 커밋되고, 풀 리퀘스트로 멘토에게
검토를 요청합니다. 셀이 오류로 멈추거나 점검에 실패하거나 시간 제한에 걸리면
아무것도 커밋하지 않습니다. 실행 기록을 읽고 노트북을 고친 뒤 다시 제출하세요.

`sgtl submit`은 비공개 GitHub 사본에만 올리고 공개 강의 저장소에는 절대 올리지 않습니다. `gh auth status`에
로그인되어 있어야 합니다([비공개 사본](git_workflow.md)).
