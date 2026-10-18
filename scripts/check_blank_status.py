import urllib.request
import json

targets = [
    {
        "dist": "종로구",
        "lcns": "20260040717",
        "uptae": "기타",
        "cases": {
            "원플러스": "경우의 수 1 (최유력 95% - 업태 '기타' 일치)",
            "브라차 안국점": "경우의 수 2 (예비 5% - 업태 '경양식')"
        }
    },
    {
        "dist": "강북구",
        "lcns": "20260076724",
        "uptae": "한식",
        "cases": {
            "오미가": "경우의 수 1 (최유력 65% - 17:54 마지막 채번, 업태 '한식')",
            "호남식당": "경우의 수 2 (유력 25% - 번동 393, 업태 '한식')",
            "소문난 왕족발 순대국": "경우의 수 3 (예비 10% - 번동 393, 업태 '한식')",
            "만두옥": "경우의 수 4 (탈락군 - 업태 기타)",
            "마을찻집 고운울림": "경우의 수 4 (탈락군 - 업태 기타)",
            "마차먹거리": "경우의 수 4 (탈락군 - 업태 소주방)",
            "민지네": "경우의 수 4 (탈락군 - 업태 기타)",
        }
    },
    {
        "dist": "강남구",
        "lcns": "20260147386",
        "uptae": "유통전문판매업",
        "cases": {
            "딩딤키친": "경우의 수 1 (최유력 90% - 대표자 소준범 1:1 일치)",
            "숨비안": "경우의 수 2 (대안 5% - 역삼동 패스트파이브)",
            "주식회사 에이더블유더블유": "경우의 수 3 (대안 5% - 역삼동 해암빌딩)"
        }
    },
    {
        "dist": "강서구",
        "lcns": "20260109491",
        "uptae": "즉석판매제조가공업",
        "cases": {
            "마켓상점": "경우의 수 1 (유력 40% - NC 강서점 B1, 17:50 채번)",
            "온정 모퉁이찬": "경우의 수 2 (유력 30% - 등촌로 개인반찬가게)",
            "(주)마켓인": "경우의 수 3 (대안 20% - 트레이더스 B2)",
            "주식회사 동일": "경우의 수 4 (대안 10% - 트레이더스 B2, 유선전화)"
        }
    }
]

print("=== 식품안전나라 10/16 빈칸 채움 실시간 검증 & 모든 경우의 수 매칭 ===")
all_blank = True

for t in targets:
    dist = t["dist"]
    lcns = t["lcns"]
    cases = t["cases"]
    url = f"http://openapi.foodsafetykorea.go.kr/api/sample/I2500/json/1/5/LCNS_NO={lcns}"
    try:
        req = urllib.request.urlopen(url, timeout=5)
        d = json.loads(req.read().decode("utf-8"))
        rows = d.get("I2500", {}).get("row", [])
        if rows:
            r = rows[0]
            bssh = r.get("BSSH_NM", "").strip()
            addr = (r.get("ADDR") or r.get("LOCP_ADDR") or "").strip()
            prsdnt = r.get("PRSDNT_NM", "").strip()
            chng = r.get("CHNG_DT", "")
            
            if bssh:
                all_blank = False
                matched_case = "⚠️ 미지의 상호명"
                for cand_name, case_desc in cases.items():
                    if cand_name in bssh or bssh in cand_name:
                        matched_case = f"🎯 {cand_name} [{case_desc}]"
                        break
                print(f"[{dist}] 인허가: {lcns} | 상호: '{bssh}' | 대표: '{prsdnt}' | 주소: '{addr}' ➔ {matched_case}")
            else:
                top_cand = list(cases.keys())[0]
                print(f"[{dist}] 인허가: {lcns} | 상태: 빈칸('') 유지 중 | 1순위: {top_cand} (후보군 {len(cases)}개 대기)")
        else:
            code = d.get("I2500", {}).get("RESULT", {}).get("CODE", "EMPTY")
            print(f"[{dist}] 인허가: {lcns} | 미조회 ({code})")
    except Exception as e:
        print(f"[{dist}] 인허가: {lcns} | 에러: {e}")

print("-" * 75)
if all_blank:
    print("👉 현재 모든 타깃이 여전히 빈칸('') 상태입니다. (식약처 배치 미반영)")
else:
    print("🎉 식약처 배치가 작동하여 상호명이 채워졌습니다! 위 매칭 결과를 확인하세요.")
