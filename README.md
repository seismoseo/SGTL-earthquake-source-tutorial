# SGTL earthquake source tutorial

A hands-on Jupyter course that takes a newcomer from earthquake catalogs and seismograms to research-level
earthquake source work: picking, location, double-difference relocation, focal mechanisms, moment tensors,
Coulomb stress and detection, built around the PocketQuake toolchain. You write the core methods yourself, first
on synthetic data with a known answer, then on real Korean data, and then you run the production tools and
explain what they did. Automatic checks compare your functions with independent references and never show you
solution code. The course runs on a shared lab server, and you work in your own private copy of this repository.

**Made by** Minseong Seo (SGTL, Seoul National University). SGTL is the Seismology, Geophysics, Tectonophysics
Laboratory.

**Acknowledgments.** Byeong-Seok Ahn (Pukyong National University) for the integrated KS/KG station metadata
(StationMetadata; Ahn, Kang & Jung, 2024, *Journal of the Geological Society of Korea* 60(1):111-119,
doi:10.14770/jgsk.2024.001), fetched from its public repository at install time. The Korea Meteorological
Administration (KMA) for the earthquake catalog, used under the Korea Open Government License Type 1, and for the
KS network data. The Korea Institute of
Geoscience and Mineral Resources (KIGAM) for the KG network data and bulletin mechanisms quoted with citation.
The U.S. Geological Survey (ComCat) and the International Seismological Centre for public catalogs. The authors
of PocketQuake, ObsPy, PyGMT/GMT, SeisBench, EQNet/PhaseNet+, HYPOINVERSE, HypoDD, SKHASH, MTUQ, PyFK,
SeismoStats (ETH Zurich, Swiss Seismological Service), Elastic_stresses_py and cutde.

> **한국어 요약.** 이 튜토리얼은 지진 목록과 지진 기록에서 출발해 연구 수준의 지진원 분석(위상 피킹, 진원 결정,
> 이중차분 진원 재결정, 단층면해, 모멘트 텐서, 쿨롱 응력, 지진 검출)까지 직접 코드를 짜며 배우는 Jupyter 실습
> 과정입니다. 모든 과제는 **예측 → 코드 작성 → 자동 점검 → 설명** 순서로 진행합니다. 점검 프로그램은 정답 코드를
> 보여 주지 않고, 합성 자료나 다른 라이브러리 같은 독립적인 기준과 비교한 결과만 알려 줍니다. AI는 답을 주는
> 도구가 아니라 개인 교사로만 쓰고, 도움 받은 내용은 `work/ai_log/`에 기록합니다. 첫날에는
> [docs/setup_ko.md](docs/setup_ko.md)를 처음부터 차례대로 따라 하세요.

## Day 1 quick start

Your mentor sits with you on day 1. The full step-by-step guide is [docs/setup.md](docs/setup.md)
(한국어: [docs/setup_ko.md](docs/setup_ko.md)).

1. On your laptop, open a terminal: **Windows** PowerShell, **macOS** Terminal, or Xshell / PuTTY.
2. Log in to the lab server with the account you were given: `ssh <your_id>@<server>`.
3. Get the tutorial and go into it:
   ```bash
   git clone https://github.com/seismoseo/SGTL-earthquake-source-tutorial.git ~/sgtl/tutorial
   cd ~/sgtl/tutorial
   ```
4. Install the course software. The first command is a dry run that only prints what it would do:
   ```bash
   bin/sgtl-install
   bin/sgtl-install --apply
   ```
5. Start JupyterLab on the server: `bin/sgtl-lab start` shows what it would do, and `bin/sgtl-lab start --apply`
   does it. It prints a tunnel command and a link.
6. Open the tunnel: in a **new terminal on your laptop**, paste the `ssh -N -L ...` command that `sgtl-lab`
   printed (Xshell and PuTTY users: follow the recipe it prints). Then open the printed `http://127.0.0.1:...`
   link in your browser.
7. Make your copy of the first module: `bin/sgtl new M00`.
8. In JupyterLab, open `work/M00_*/M00_*.ipynb`, choose the kernel **SGTL (Python 3.12)**, and start reading.

The tools that install software, start or stop JupyterLab, change your git setup or copy files into your home
folder are **dry runs** unless you add `--apply`, so you can look before you act: `bin/sgtl-install`,
`bin/sgtl-lab start` and `stop`, `bin/make-private-copy`, `bin/update-from-upstream` and `bin/sgtl setup-ai`.
`bin/sgtl new MXX` acts at once, because it only copies the module notebook (and a new AI-log file) into
`work/` and never overwrites a file that is already there. `bin/sgtl doctor`, `bin/sgtl status` and
`bin/sgtl diff` only look.

## What you need

- An account on the lab server (your mentor gives you one; you change the password on first login).
- A GitHub account with two-factor authentication turned on (M00 shows you how to make your private copy).
- Later (module M03): a personal STP account for waveform data and the STP program, both from the lab.
  Waveforms never go into this repository.

## Course map

About 35-40 hours per week. Times are estimates; the plan is adjusted after week 1. Details: [docs/curriculum.md](docs/curriculum.md).

| Week | Module | What you learn |
|---|---|---|
| 1 | M00 Start here | The shared server, terminal, SSH tunnel, git and your private copy, installing the software |
| 1 | M01 Python for earthquake catalogs | pandas tables, functions, arrays and distances on a real catalog |
| 1 | M02 Figures and maps | Clear Matplotlib figures and PyGMT maps in the house style |
| 1 | M04 Earthquake catalogs | Who makes catalogs and what they hold; the KMA list's precision and quirks; magnitude-frequency counts, sequences in UTC, pairing two catalogs, completeness by network epoch |
| 2 | M05 Statistical seismology | b-value and its uncertainty, completeness, b-positive, Omori-Utsu aftershock decay, declustering; checked against SeismoStats |
| 2 | M03 Getting seismic data | Network, station and channel codes; time windows in UTC; fetching waveforms with your own STP account (`bin/sgtl data`); response epochs, sensitivity and removing the response |
| 2 | M10 Seismograms | SAC headers and time, filters and spectra, removing the response checked on two instruments, rotation, S-P distances and record sections, thread limits |
| 3 | M20 Picking arrivals | STA/LTA triggers and onset times; how filters move automatic picks; P and S picks by hand with uncertainties and polarities (picker E2) |
| 3 | M21 Deep-learning pickers | Picks from probability curves; two pretrained PhaseNet models against your picks; PocketQuake's picking stage, rerun and changed; first motions |
| 3 | M22 Detection (stretch) | Finding small earthquakes in continuous data |
| 3 | M30 Travel times in a layered crust | Direct-wave times in layered models (head waves only as an idea), the Wadati diagram from your picks, residuals of two velocity models, TauP |
| 4 | M31 Earthquake location | Grid search, Geiger's method and location uncertainty |
| 4 | M32 HYPOINVERSE via PocketQuake | Running a production locator and comparing it with yours |
| 5 | M41 Relative relocation | Differential times, cross-correlation, the double-difference system, bootstrap; HypoDD via PocketQuake |
| 6 | M50 The focal sphere | Strike, dip and rake, nodal planes and beachballs, by hand first |
| 6 | M51 Mechanisms from polarities | Grid search over mechanisms, SKHASH, and the S/P amplitude trap |
| 6 | M52 Synthetic seismograms | Moment tensors, M0 and Mw, radiation patterns, point-source synthetics checked against PyFK |
| 7 | M53 Moment tensor inversion | Least squares on synthetics, norms and time shifts, Kagan angle, the lune; MTUQ on a real event |
| 7 | M54 Coulomb stress change | Stress changes from synthetic faults; when they can and cannot be seen (Gyeongju 2016) |
| 8 | M60 Full run and project plan | The whole chain on a new sequence; planning your research project |
| 9-13 | Project | The Suncheon microearthquake sequence: depths, fault geometry, mechanisms; report, lab talk and oral defense |

## How the work goes

Each task follows the same rhythm (details: [docs/how_this_tutorial_works.md](docs/how_this_tutorial_works.md)):

1. **Predict**: write what you expect in `st.predict("MXX-Tn", """ ... """)` before you code.
2. **Code**: fill in the function where it says `# YOUR CODE HERE`.
3. **Check**: run the check cell. It prints PASS or FAIL, how many cases passed and a fixed message about the
   kind of mistake. It never shows solution code or hidden real-data answers.
4. **Explain**: answer the Explain prompt in 3-5 sentences, using only numbers your notebook printed.

Stuck? `st.hint("MXX-Tn", 1)`; levels 2 and 3 unlock after failed checks. AI tools are allowed as a tutor, not as
an answer key: read [docs/ai_policy.md](docs/ai_policy.md) and log AI help in `work/ai_log/`. Share the server
fairly: [docs/server_manners.md](docs/server_manners.md). Data rules: [docs/data_policy.md](docs/data_policy.md).

## Licenses

- **Code**: MIT License ([LICENSE](LICENSE)).
- **Text and figures**: CC BY 4.0 ([LICENSE-CONTENT.md](LICENSE-CONTENT.md)).
- **Data are not covered** by either license and keep their sources' terms. The KMA catalog subsets in
  `data/catalogs/` are used under the Korea Open Government License (KOGL) Type 1 (attribution):
  - 이 저작물은 기상청이 공공누리 제1유형(출처표시)으로 개방한 '국내지진 목록'을 이용하였으며, 해당 저작물은
    기상청 날씨누리(<https://www.weather.go.kr>)에서 무료로 내려받을 수 있습니다.
  - This work uses the domestic earthquake catalog of the Korea Meteorological Administration (KMA), released under
    the Korea Open Government License Type 1 (attribution). It can be downloaded free of charge from the KMA website
    (<https://www.weather.go.kr>).

## How to cite

Use [CITATION.cff](CITATION.cff); on GitHub, the "Cite this repository" button gives APA and BibTeX. For example:
Seo, M. (2026). *SGTL earthquake source tutorial* (version 0.3.0). Seismology, Geophysics, Tectonophysics
Laboratory, Seoul National University. <https://github.com/seismoseo/SGTL-earthquake-source-tutorial>.
People who helped are listed in [AUTHORS.md](AUTHORS.md).
