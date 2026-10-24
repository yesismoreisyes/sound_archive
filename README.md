# Sound Archive — Daum Kim

유리된 것들의 가청화 / The Audibilization of the Unmoored

휴대용 릴 테이프 데크로 작업 음원을 재생하는 사운드 아카이브입니다. 서버 없이 GitHub Pages에서 동작합니다.

## 조작

| 조작 | 기능 |
|---|---|
| A | 재생 (재생하는 동안 눌린 채로 유지) |
| B | 정지 (같은 위치에서 이어 재생) |
| C | 다음 음원 |
| D | 이전 음원 (3초 넘게 재생 중이면 곡 처음으로) |
| VOLUME 노브 | 볼륨 |
| TAPE SPEED 노브 | 3¾–15 IPS. 실제 테이프처럼 음높이도 함께 바뀜. 더블클릭하면 7½로 복귀 |

노브는 위아래 드래그, 마우스 휠, 방향키로 돌립니다. 키보드: Space 재생/정지, ← 이전, → 다음.

## 음원과 배경 바꾸기

1. `audio/` 폴더에 음원(mp3 권장, 192kbps 정도)을 넣습니다. 파일 이름은 영문·숫자로 (예: `01-blood-harmony.mp3`).
2. `bg/` 폴더에 트랙별 배경 이미지를 넣습니다 (jpg 또는 webp, 가로 1920px 정도).
3. `index.html`에서 `const TRACKS = [` 부분을 고칩니다.

```js
const TRACKS = [
  { title: "혈연의 하모니", meta: "2025 · AI 음성, NARA RG 242", src: "audio/01-blood-harmony.mp3", bg: "bg/01.jpg" },
  { title: "대외비",        meta: "2024 · 서피스 익사이터",       src: "audio/02-eyes-only.mp3",     bg: "bg/02.jpg" },
  // 10~20개
];
```

- `src: null` 이면 브라우저에서 만든 데모 음원이 재생됩니다.
- 트랙이 바뀌면 배경이 1.4초 동안 천천히 바뀝니다.
- 공간 음향(Ambisonics, 다채널) 원본은 웹에서 스테레오로만 재생되므로 바이노럴 또는 스테레오 다운믹스를 올리세요.

## 데크 이미지 (`deck/`)

Blender 스크립트 `tape_deck.py`로 렌더한 레이어입니다. 웹페이지가 이 레이어를 겹치고, 감긴 테이프·테이프 띠·미터 바늘·카운터 글자는 `layout.json`의 카메라 투영 정보로 직접 그립니다.

| 파일 | 내용 |
|---|---|
| `plate.webp` | 본체 (투명 배경 + 바닥 그림자) |
| `reel_L.webp`, `reel_R.webp` | 투명 릴 회전 30프레임 (120°) |
| `knob_volume.webp`, `knob_speed.webp` | 노브 48프레임 |
| `key_A_down.webp` … `key_D_down.webp` | 눌린 버튼 |
| `glass_L.webp`, `glass_R.webp` | 미터 유리와 테두리 |
| `pinch.webp` | 테이프 앞 핀치 롤러 |
| `roller_top_L.webp`, `roller_top_R.webp` | 가이드 롤러 위 플랜지 (테이프 위에 덮어 그림) |
| `layout.json` | 레이어 위치, 카메라 투영 행렬 |

모양이나 각도를 바꾸려면 Blender에서 다시 렌더하고 이 폴더의 파일만 교체하면 됩니다. 본체만 바뀌었으면 `MODE = "plate"`(5분)로 충분합니다.

## 공개하기 (GitHub Pages)

Settings → Pages → Source: `Deploy from a branch`, Branch: `main` / `/ (root)` → Save.
1~2분 뒤 `https://yesismoreisyes.github.io/sound_archive/` 에서 열립니다.

`sound.kimdaum.com` 으로 연결하려면:
1. kimdaum.com 도메인 회사의 DNS 설정에 `CNAME` 레코드 추가 — 이름 `sound`, 값 `yesismoreisyes.github.io`
2. Settings → Pages → Custom domain 에 `sound.kimdaum.com` 입력 → 저장 → 잠시 뒤 Enforce HTTPS 체크

## 저작권

이 저장소의 음원, 이미지, 렌더는 김다움(Daum Kim)에게 모든 권리가 있습니다.
