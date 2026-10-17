// Cloudflare Pages Function: /api/businesses
export async function onRequestGet(context) {
  const { request, env } = context;
  const reqUrl = new URL(request.url);
  const sidoParam = reqUrl.searchParams.get("sido") || "all";
  const countParam = reqUrl.searchParams.get("count") || "10";

  const sidoMap = {
    seoul: "11",
    gyeonggi: "41",
    all: "all"
  };
  const sidoCd = sidoMap[sidoParam] || sidoParam;

  const BASE_URL = "https://www.foodsafetykorea.go.kr";
  const MAIN_PAGE_URL = `${BASE_URL}/portal/specialinfo/searchInfoCompany.do`;
  const LIST_URL = `${BASE_URL}/ajax/portal/specialinfo/searchBsnList.do`;
  const CNT_URL = `${BASE_URL}/ajax/portal/specialinfo/searchBsnListCnt.do`;
  const DETAIL_URL = `${BASE_URL}/potalPopup/fooddanger/bsnInfoDetail.do`;

  const commonHeaders = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
  };

  try {
    let listData = null;
    let totalRegionCount = null;
    let callPage = "";
    let cookieStr = "";

    const postParamsObj = {
      s_mode: "1",
      s_opt: "all",
      s_induty_cd: "all",
      s_sido_cd: sidoCd,
      s_opt1: "N",
      s_opt2: "N",
      s_opt3: "N",
      s_opt4: "",
      s_keyword: "",
      s_opt5: "N",
      s_opt6: "1",
      s_opt7: "N",
      s_order_by: "reg_dt",
      s_list_cnt: String(countParam),
      s_page_num: "1",
      s_tx_id: "1"
    };

    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const initRes = await fetch(MAIN_PAGE_URL, { headers: commonHeaders });
        const initHtml = await initRes.text();
        const callPageMatch = initHtml.match(/id=["']callPage["']\s+value=["']([^"']+)["']/);
        callPage = callPageMatch ? callPageMatch[1] : "";
        if (!callPage) continue;

        const rawCookies = typeof initRes.headers.getSetCookie === "function"
          ? initRes.headers.getSetCookie()
          : (initRes.headers.get("set-cookie") ? [initRes.headers.get("set-cookie")] : []);

        const parsedCookies = ["callPage=" + callPage];
        for (const c of rawCookies) {
          const part = c.split(";")[0].trim();
          if (part) parsedCookies.push(part);
        }
        cookieStr = parsedCookies.join("; ");

        const postBody = new URLSearchParams({
          ...postParamsObj,
          callPage: callPage
        });

        const reqHeaders = {
          ...commonHeaders,
          "Referer": MAIN_PAGE_URL,
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
          "Cookie": cookieStr
        };

        const [listRes, cntRes] = await Promise.all([
          fetch(`${LIST_URL}?callPage=${callPage}`, {
            method: "POST",
            headers: reqHeaders,
            body: postBody.toString()
          }),
          fetch(`${CNT_URL}?callPage=${callPage}`, {
            method: "POST",
            headers: reqHeaders,
            body: postBody.toString()
          }).catch(() => null)
        ]);

        if (cntRes) {
          try {
            const cntJson = await cntRes.json();
            if (cntJson && typeof cntJson.totCnt !== "undefined") {
              totalRegionCount = Number(cntJson.totCnt);
            }
          } catch (e) {}
        }

        const listText = await listRes.text();
        if (!listText || listText.trim() === "" || listText.startsWith("\u0000")) {
          continue;
        }

        listData = JSON.parse(listText);
        if (listData && listData.bsnList) {
          break;
        }
      } catch (err) {
        if (attempt === 2) throw err;
      }
    }

    if (!listData || !listData.bsnList) {
      throw new Error("식품안전나라 서버 일시 지연 (잠시 후 다시 시도해 주세요)");
    }

    const rawList = listData.bsnList || [];

    // Check OpenAPI I2500 today's CHNG_DT status in parallel (with 5-min KV cache)
    const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
    const todayKst = kstNow.toISOString().slice(0, 10).replace(/-/g, "");
    const openApiStatusPromise = (async () => {
      const cacheKey = `openapi_today:${todayKst}`;
      if (env && env.DETECTED_STORES) {
        try {
          const cached = await env.DETECTED_STORES.get(cacheKey);
          if (cached) return JSON.parse(cached);
        } catch (e) {}
      }
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6500);
        const res = await fetch(`http://openapi.foodsafetykorea.go.kr/api/sample/I2500/json/1/1/CHNG_DT=${todayKst}`, {
          signal: controller.signal
        });
        clearTimeout(timeoutId);
        const json = await res.json();
        const info = json?.I2500;
        const code = info?.RESULT?.CODE || json?.RESULT?.CODE || "UNKNOWN";
        const msg = info?.RESULT?.MSG || json?.RESULT?.MSG || "";
        const totalCount = info?.total_count ? Number(info.total_count) : 0;
        const resultObj = {
          date_kst: `${todayKst.slice(0, 4)}-${todayKst.slice(4, 6)}-${todayKst.slice(6, 8)}`,
          code,
          msg,
          total_count: totalCount,
          is_open: code === "INFO-000" || code === "INFO-200"
        };
        if (env && env.DETECTED_STORES && (code === "INFO-000" || code === "INFO-700" || code === "INFO-200")) {
          const putP = env.DETECTED_STORES.put(cacheKey, JSON.stringify(resultObj), { expirationTtl: 300 });
          if (context.waitUntil) context.waitUntil(putP);
          else await putP;
        }
        return resultObj;
      } catch (e) {
        return {
          date_kst: `${todayKst.slice(0, 4)}-${todayKst.slice(4, 6)}-${todayKst.slice(6, 8)}`,
          code: "TIMEOUT",
          msg: "OpenAPI 응답 지연",
          total_count: null,
          is_open: null
        };
      }
    })();

    // Pre-verified PRMS_DT (인허가일자) from Food Safety Korea OpenAPI I2500
    const VERIFIED_PRMS_DT = {
      "20260051013": "2026-10-16",
      "20260123112": "2026-10-16",
      "20260109489": "2026-10-16",
      "20260109490": "2026-10-16",
      "20260076723": "2026-10-16",
      "20260147385": "2026-10-16"
    };

    // Process items in parallel with per-request timeout
    const itemsToProcess = rawList.slice(0, Math.min(parseInt(countParam, 10) || 10, 25));
    const [results, openApiToday] = await Promise.all([
      Promise.all(itemsToProcess.map(async (item) => {
        const ledgNo = item.BSN_LCNS_LEDG_NO || "";
        const lcnsNo = item.LCNS_NO || "";
        let storeName = (item.BSSH_NM && item.BSSH_NM !== "NULL") ? item.BSSH_NM.trim() : "";
        let address = (item.SITE_ADDR && item.SITE_ADDR !== "NULL") ? item.SITE_ADDR.trim() : "";

        if (!storeName && ledgNo) {
          try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2500);
            const detRes = await fetch(`${DETAIL_URL}?bsnLcnsLedgNo=${ledgNo}&callPage=${callPage}`, {
              headers: {
                ...commonHeaders,
                "Referer": MAIN_PAGE_URL,
                "Cookie": cookieStr
              },
              signal: controller.signal
            });
            clearTimeout(timeoutId);
            const detHtml = await detRes.text();
            const nameMatch = detHtml.match(/<th[^>]*>\s*업체명\s*<\/th>\s*<td[^>]*>([\s\S]*?)<\/td>/i);
            if (nameMatch) {
              const parsedName = nameMatch[1].replace(/<[^>]+>/g, "").trim();
              if (parsedName) storeName = parsedName;
            }
            if (!address) {
              const addrMatch = detHtml.match(/<th[^>]*>\s*소재지\s*<\/th>\s*<td[^>]*>([\s\S]*?)<\/td>/i);
              if (addrMatch) {
                const parsedAddr = addrMatch[1].replace(/<[^>]+>/g, "").trim();
                if (parsedAddr) address = parsedAddr;
              }
            }
          } catch (e) {
            // keep fallback
          }
        }

        // Fetch or resolve real permit date (PRMS_DT) from OpenAPI I2500 + KV cache
        let permitDate = VERIFIED_PRMS_DT[lcnsNo] || null;
        if (!permitDate && lcnsNo) {
          if (env && env.DETECTED_STORES) {
            try {
              permitDate = await env.DETECTED_STORES.get(`prms:${lcnsNo}`);
            } catch (e) {}
          }
          if (!permitDate) {
            try {
              const controller = new AbortController();
              const timeoutId = setTimeout(() => controller.abort(), 2000);
              const apiRes = await fetch(`http://openapi.foodsafetykorea.go.kr/api/sample/I2500/json/1/5/LCNS_NO=${lcnsNo}`, {
                signal: controller.signal
              });
              clearTimeout(timeoutId);
              const apiJson = await apiRes.json();
              const row0 = apiJson?.I2500?.row?.[0];
              const rawPrms = row0?.PRMS_DT;
              if (!storeName && row0?.BSSH_NM) {
                storeName = row0.BSSH_NM.trim();
              }
              if (!address && row0?.ADDR) {
                address = row0.ADDR.trim();
              }
              if (rawPrms && rawPrms.length === 8) {
                permitDate = `${rawPrms.slice(0, 4)}-${rawPrms.slice(4, 6)}-${rawPrms.slice(6, 8)}`;
                if (env && env.DETECTED_STORES) {
                  const putPromise = env.DETECTED_STORES.put(`prms:${lcnsNo}`, permitDate);
                  if (context.waitUntil) context.waitUntil(putPromise);
                  else await putPromise;
                }
              }
            } catch (e) {}
          }
        }

        let detectedAt = null;
        if (env && env.DETECTED_STORES && ledgNo) {
          try {
            detectedAt = await env.DETECTED_STORES.get(`store:${ledgNo}`);
            if (!detectedAt) {
              detectedAt = new Date().toISOString();
              if (context.waitUntil) {
                context.waitUntil(env.DETECTED_STORES.put(`store:${ledgNo}`, detectedAt));
              } else {
                await env.DETECTED_STORES.put(`store:${ledgNo}`, detectedAt);
              }
            }
          } catch (kvErr) {
            detectedAt = new Date().toISOString();
          }
        } else {
          detectedAt = new Date().toISOString();
        }

        const isPendingName = !storeName;

        return {
          license_no: lcnsNo,
          store_name: storeName || "신규 채번 (상호·주소 반영 대기중)",
          is_pending_name: isPendingName,
          industry: item.INDUTY_CD_NM || "기타",
          district: item.INSTT_CD_NM || "",
          address: address || (isPendingName ? "소재지 반영 대기중" : ""),
          representative: item.PRSDNT_NM || "",
          status: item.CLSBIZ_DVS_CD_NM || "정상",
          ledger_no: ledgNo,
          permit_date: permitDate,
          detected_at: detectedAt
        };
      })),
      openApiStatusPromise
    ]);

    const maxLedgerNo = results.reduce((max, r) => {
      if (r.ledger_no && r.ledger_no > max) return r.ledger_no;
      return max;
    }, "");

    return new Response(JSON.stringify({
      success: true,
      region: sidoParam,
      total_region_count: totalRegionCount,
      max_ledger_no: maxLedgerNo || null,
      openapi_today: openApiToday,
      count: results.length,
      updated_at: new Date().toISOString(),
      data: results
    }), {
      headers: {
        "Content-Type": "application/json; charset=UTF-8",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=15"
      }
    });

  } catch (error) {
    return new Response(JSON.stringify({
      success: false,
      error: error.message
    }), {
      status: 500,
      headers: { "Content-Type": "application/json; charset=UTF-8" }
    });
  }
}
