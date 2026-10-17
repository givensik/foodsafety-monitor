#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
식품안전나라 신규 인허가 업체 실시간 감지 및 등록 시각 모니터링 스크립트
"""

import time
import datetime
import csv
import os
import re
import requests
import urllib3

# SSL 경고 무시 (공공기관 인증서 호환용)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.foodsafetykorea.go.kr"
MAIN_PAGE_URL = f"{BASE_URL}/portal/specialinfo/searchInfoCompany.do"
LIST_URL = f"{BASE_URL}/ajax/portal/specialinfo/searchBsnList.do"
CNT_URL = f"{BASE_URL}/ajax/portal/specialinfo/searchBsnListCnt.do"
DETAIL_URL = f"{BASE_URL}/potalPopup/fooddanger/bsnInfoDetail.do"
OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "new_businesses.csv")


class FoodSafetyMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.call_page = None
        self.last_top_id = None

    def refresh_session(self):
        """메인 페이지 방문하여 세션 쿠키 및 callPage 갱신"""
        resp = self.session.get(MAIN_PAGE_URL, timeout=15)
        m = re.search(r'id=[\"\']callPage[\"\']\s+value=[\"\']([^\"\']+)[\"\']', resp.text)
        if m:
            self.call_page = m.group(1)
            self.session.cookies.set("callPage", self.call_page, domain="www.foodsafetykorea.go.kr", path="/")
        else:
            raise RuntimeError("callPage 파싱 실패")

    def get_total_count(self, sido="all"):
        """현재 등록된 총 업체 수 조회 (sido: all, 11(서울), 41(경기) 등)"""
        if not self.call_page:
            self.refresh_session()

        headers = {
            "Referer": MAIN_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        data = {
            "s_mode": "1",
            "s_opt": "all",
            "s_induty_cd": "all",
            "s_sido_cd": sido,
            "s_opt6": "1",
            "s_tx_id": "1",
            "callPage": self.call_page,
        }
        res = self.session.post(f"{CNT_URL}?callPage={self.call_page}", data=data, headers=headers, timeout=15)
        res_json = res.json()
        return res_json.get("totCnt", 0)

    def fetch_latest_businesses(self, count=5, sido="all"):
        """최신 등록순(reg_dt 내림차순)으로 업체 목록 조회 (sido: all, 11(서울), 41(경기) 등)"""
        if not self.call_page:
            self.refresh_session()

        headers = {
            "Referer": MAIN_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        data = {
            "s_mode": "1",
            "s_opt": "all",
            "s_induty_cd": "all",
            "s_sido_cd": sido,
            "s_opt1": "N",
            "s_opt2": "N",
            "s_opt3": "N",
            "s_opt4": "",
            "s_keyword": "",
            "s_opt5": "N",
            "s_opt6": "1",
            "s_opt7": "N",
            "s_order_by": "reg_dt",
            "s_list_cnt": str(count),
            "s_page_num": "1",
            "s_tx_id": "1",
            "callPage": self.call_page,
        }
        res = self.session.post(f"{LIST_URL}?callPage={self.call_page}", data=data, headers=headers, timeout=45)
        data = res.json()
        return data.get("bsnList", [])

    def fetch_detail_name(self, ledg_no):
        """대장번호로 상세 팝업을 호출하여 상호명 파싱"""
        url = f"{DETAIL_URL}?bsnLcnsLedgNo={ledg_no}&callPage={self.call_page}"
        headers = {"Referer": MAIN_PAGE_URL}
        try:
            r = self.session.get(url, headers=headers, timeout=10)
            pairs = re.findall(r'<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
            for th, td in pairs:
                k = re.sub(r'<[^>]+>', '', th).strip()
                v = re.sub(r'<[^>]+>', '', td).strip()
                if k == "업체명":
                    return v
        except Exception:
            pass
        return "상호명 미기재"

    def save_to_csv(self, row):
        """CSV 파일에 기록"""
        file_exists = os.path.exists(OUTPUT_CSV)
        with open(OUTPUT_CSV, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "감지일시(몇시에 등록되었는지)",
                    "인허가번호",
                    "업체명",
                    "업종",
                    "관할지자체",
                    "소재지",
                    "대표자(마스킹)",
                    "상태",
                    "대장번호"
                ])
            writer.writerow(row)

    def check_once(self, sido="all"):
        """1회 점검 실행"""
        sido_label = "전체" if sido == "all" else ("서울" if sido == "11" else ("경기" if sido == "41" else sido))
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] 최신 업체 현황 확인 중... (지역: {sido_label})")
        tot_cnt = self.get_total_count(sido=sido)
        latest = self.fetch_latest_businesses(count=5, sido=sido)

        if not latest:
            print("  조회된 결과가 없습니다.")
            return

        current_top_id = latest[0].get("BSN_LCNS_LEDG_NO")
        print(f"  현재 총 등록 건수: {tot_cnt:,}건")
        print(f"  최신 인허가 대장번호: {current_top_id}")

        for idx, item in enumerate(latest, 1):
            ledg_no = item.get("BSN_LCNS_LEDG_NO")
            name = self.fetch_detail_name(ledg_no)
            item_time = now_str
            print(f"  [{idx}] [{item_time}] {item.get('LCNS_NO')} | {name} | {item.get('INDUTY_CD_NM')} | {item.get('INSTT_CD_NM')} | {item.get('SITE_ADDR')}")

    def monitor_loop(self, interval_seconds=60, sido="all"):
        """지정된 주기(기본 60초)마다 모니터링하여 새 업체가 들어오는 정확한 시각 포착"""
        sido_label = "전체" if sido == "all" else ("서울" if sido == "11" else ("경기" if sido == "41" else sido))
        print(f"=== 신규 업체 등록 감지 모니터링 시작 (지역: {sido_label}, 주기: {interval_seconds}초) ===")
        self.refresh_session()

        # 최초 기준점 설정
        latest = self.fetch_latest_businesses(count=1, sido=sido)
        if latest:
            self.last_top_id = latest[0].get("BSN_LCNS_LEDG_NO")
            print(f"초기 최신 대장번호: {self.last_top_id}")

        while True:
            try:
                time.sleep(interval_seconds)
                now_dt = datetime.datetime.now()
                now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

                latest = self.fetch_latest_businesses(count=5, sido=sido)
                if not latest:
                    continue

                new_items = []
                for item in latest:
                    item_id = item.get("BSN_LCNS_LEDG_NO")
                    if item_id == self.last_top_id:
                        break
                    new_items.append(item)

                if new_items:
                    print("\n" + "=" * 60)
                    print(f"🚨 [신규 등록 감지!] 포착 시각: {now_str} (총 {len(new_items)}건)")
                    print("=" * 60)
                    for item in reversed(new_items):
                        ledg_no = item.get("BSN_LCNS_LEDG_NO")
                        name = self.fetch_detail_name(ledg_no)
                        lcns_no = item.get("LCNS_NO")
                        induty = item.get("INDUTY_CD_NM")
                        instt = item.get("INSTT_CD_NM")
                        addr = item.get("SITE_ADDR")
                        prsdnt = item.get("PRSDNT_NM")
                        status = item.get("CLSBIZ_DVS_CD_NM")

                        print(f"  👉 [{now_str}] {lcns_no} | {name} | {induty} | {instt} | {addr}")
                        self.save_to_csv([
                            now_str, lcns_no, name, induty, instt, addr, prsdnt, status, ledg_no
                        ])

                    self.last_top_id = latest[0].get("BSN_LCNS_LEDG_NO")
                else:
                    print(f"[{now_str}] 변동 없음 (최신: {self.last_top_id})")

            except Exception as e:
                print(f"[오류 발생] {e}, 세션 재연결 시도...")
                try:
                    self.refresh_session()
                except Exception:
                    pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="식품안전나라 신규 업체 모니터링")
    parser.add_argument("action", nargs="?", default="check", choices=["check", "run"], help="check: 1회 확인, run: 지속 모니터링")
    parser.add_argument("--sido", default="all", choices=["all", "11", "41", "seoul", "gyeonggi"], help="지역 선택 (11/seoul: 서울, 41/gyeonggi: 경기, all: 전국)")
    parser.add_argument("--interval", type=int, default=60, help="모니터링 주기(초)")
    args = parser.parse_args()

    sido_map = {"seoul": "11", "gyeonggi": "41"}
    sido_val = sido_map.get(args.sido, args.sido)

    monitor = FoodSafetyMonitor()
    if args.action == "run":
        monitor.monitor_loop(interval_seconds=args.interval, sido=sido_val)
    else:
        monitor.check_once(sido=sido_val)

