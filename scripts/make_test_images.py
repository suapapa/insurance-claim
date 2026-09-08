"""CJK 폰트로 서류 풍 테스트 이미지를 생성하는 스크립트.

사용: uv run python scripts/make_test_images.py  -> /tmp/test_docs/*.jpg
"""
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/google-noto-sans-mono-cjk-vf-fonts/NotoSansMonoCJK-VF.ttc"

DOCS = {
    "diag_kim": [
        ("진 단 서", 40),
        ("환자명: 김철수 (남, 45세)", 24),
        ("발급일: 2026-08-10", 24),
        ("상 병 명: 요추 염좌 (S33.5)", 28),
        ("사고경위: 2026-08-08 14:30경 회사 계단에서", 22),
        ("미끄러져 넘어져 허리를 다침", 22),
        ("사고장소: 서울 강남구 테헤란로 123", 22),
        ("치 료 기 간: 2026-08-08 ~ 2026-08-20 (통원)", 22),
    ],
    "rx_kim": [
        ("처 방 전", 40),
        ("환자: 김철수", 26),
        ("조제일: 2026-08-12", 24),
        ("진단: 요추 염좌", 26),
        ("복약일수: 7일", 24),
        ("○○약국", 22),
    ],
    "diag_park": [
        ("진료비 영수증", 36),
        ("환자: 박영희 (여, 60세)", 24),
        ("내원일: 2026-07-02", 24),
        ("상병: 급성 기관지염 (J20)", 26),
        ("입원구분: 외래(통원)", 24),
        ("○○내과", 22),
    ],
}


def make(name: str, lines: list[tuple[str, int]]) -> str:
    img = Image.new("RGB", (900, 620), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 890, 610], outline="#444", width=3)
    y = 70
    for text, size in lines:
        f = ImageFont.truetype(FONT, size)
        d.text((70, y), text, fill="black", font=f)
        y += size + 34
    out = f"/tmp/test_docs/{name}.jpg"
    img.save(out, quality=90)
    return out


if __name__ == "__main__":
    import os
    os.makedirs("/tmp/test_docs", exist_ok=True)
    for name, lines in DOCS.items():
        print(make(name, lines))
