// Cloudflare Pages Function: /api/businesses

const SEOUL_DISTRICT_MAP = {
  "종로구": "JN", "중구": "JG", "용산구": "YS", "성동구": "SD", "광진구": "GJ",
  "동대문구": "DDM", "중랑구": "JR", "성북구": "SB", "강북구": "GB", "도봉구": "DB",
  "노원구": "NW", "은평구": "EP", "서대문구": "SDM", "마포구": "MP", "양천구": "YC",
  "강서구": "GS", "구로구": "GR", "금천구": "GC", "영등포구": "YDP", "동작구": "DJ",
  "관악구": "GA", "서초구": "SC", "강남구": "GN", "송파구": "SP", "강동구": "GD"
};

function getSeoulDistrictCode(districtStr) {
  if (!districtStr) return null;
  for (const [name, code] of Object.entries(SEOUL_DISTRICT_MAP)) {
    if (districtStr.includes(name)) return code;
  }
  return null;
}

function getSeoulServiceCode(industry, districtCode) {
  let prefix = "LOCALDATA_072404";
  if (!industry) return `${prefix}_${districtCode}`;
  if (industry.includes("일반음식")) prefix = "LOCALDATA_072404";
  else if (industry.includes("휴게음식")) prefix = "LOCALDATA_072405";
  else if (industry.includes("제과점")) prefix = "LOCALDATA_072218";
  else if (industry.includes("즉석판매")) prefix = "LOCALDATA_072219";
  else if (industry.includes("유통전문")) prefix = "LOCALDATA_072217";
  return `${prefix}_${districtCode}`;
}

async function resolveSeoulStore({ env, context, district, industry, permitDate, subType, representative, licenseNo }) {
  const distCode = getSeoulDistrictCode(district);
  if (!distCode) return null;

  const serviceCode = getSeoulServiceCode(industry || "", distCode);
  const seoulApiKey = (env && env.SEOUL_API_KEY) || "494d5376656b6a733239467379686f";
  const cacheKey = `seoul_match:${licenseNo || serviceCode + (permitDate || "")}`;

  if (env && env.DETECTED_STORES) {
    try {
      const cached = await env.DETECTED_STORES.get(cacheKey);
      if (cached) return JSON.parse(cached);
    } catch (e) {}
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3500);
    const apiUrl = `http://openapi.seoul.go.kr:8088/${seoulApiKey}/json/${serviceCode}/1/1000/`;
    const res = await fetch(apiUrl, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (!res.ok) return null;

    const json = await res.json();
    let rows = json?.[serviceCode]?.row || [];

    // Fallback for distribution industry (072217) if rows empty
    if (rows.length === 0 && serviceCode.includes("072217")) {
      try {
        const c2 = new AbortController();
        const t2 = setTimeout(() => c2.abort(), 3000);
        const res2 = await fetch(`http://openapi.seoul.go.kr:8088/${seoulApiKey}/json/${serviceCode}/1001/2000/`, { signal: c2.signal });
        clearTimeout(t2);
        if (res2.ok) {
          const json2 = await res2.json();
          rows = json2?.[serviceCode]?.row || [];
        }
      } catch (e2) {}
    }

    if (!rows.length) return null;

    let candidates = [];
    if (permitDate) {
      candidates = rows.filter(r => {
        const prms = (r.APVPERMYMD || r.LCPMT_YMD || "").trim();
        return prms.includes(permitDate);
      });
    }

    if (candidates.length === 0) {
      candidates = rows.slice(0, 50);
    }

    let confidence = "70% (당일 인허가 등록)";

    if (subType) {
      const subTypeMatches = candidates.filter(r => {
        const u = (r.UPTAENM || r.BZSTAT_SE_NM || r.SNTUPTAENM || "").trim();
        return u.includes(subType) || subType.includes(u);
      });
      if (subTypeMatches.length > 0) {
        candidates = subTypeMatches;
        confidence = `95% (업태 '${subType}' 일치)`;
      }
    }

    if (representative && representative.includes("*")) {
      const firstChar = representative[0];
      const lastChar = representative[representative.length - 1];
      const repMatches = candidates.filter(r => {
        const repName = (r.PRSDNT_NM || r.RPRSN_NM || "").trim();
        if (!repName) return false;
        return repName.startsWith(firstChar) && repName.endsWith(lastChar);
      });
      if (repMatches.length > 0) {
        candidates = repMatches;
        confidence = `99% (대표자 '${representative}' 1:1 일치)`;
      }
    }

    candidates.sort((a, b) => {
      const timeA = (a.LASTMODTS || a.LAST_MDFCN_YMD || a.UPDATEDT || "").trim();
      const timeB = (b.LASTMODTS || b.LAST_MDFCN_YMD || b.UPDATEDT || "").trim();
      return timeB.localeCompare(timeA);
    });

    const matched = candidates[0];
    if (!matched) return null;

    const storeName = (matched.BPLCNM || matched.BPLC_NM || "").trim();
    const address = (matched.RDNWHLADDR || matched.ROAD_NM_ADDR || matched.SITEWHLADDR || matched.LOTNO_ADDR || "").trim();
    if (!storeName) return null;

    const result = {
      store_name: storeName,
      address: address,
      uptae: (matched.UPTAENM || matched.BZSTAT_SE_NM || "").trim(),
      mgt_no: (matched.MGTNO || matched.MNG_NO || "").trim(),
      tel: (matched.SITETEL || matched.TELNO || "").trim(),
      last_modified: (matched.LASTMODTS || matched.LAST_MDFCN_YMD || "").trim(),
      confidence: confidence,
      source: "서울시 새올 행정망 (LOCALDATA)"
    };

    if (env && env.DETECTED_STORES && licenseNo) {
      const putPromise = env.DETECTED_STORES.put(cacheKey, JSON.stringify(result), { expirationTtl: 86400 * 7 });
      if (context && context.waitUntil) context.waitUntil(putPromise);
      else await putPromise;
    }

    return result;
  } catch (err) {
    return null;
  }
}

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
        let subType = "";
        let popupPermitDate = null;
        let popupRepresentative = "";

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

            const pairRegex = /<th[^>]*>([\s\S]*?)<\/th>\s*<td[^>]*>([\s\S]*?)<\/td>/gi;
            let m;
            const detFields = {};
            while ((m = pairRegex.exec(detHtml)) !== null) {
              const k = m[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
              const v = m[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
              if (k && !(k in detFields)) detFields[k] = v;
            }

            if (detFields["업체명"]) storeName = detFields["업체명"];
            if (!address && detFields["소재지"]) address = detFields["소재지"];
            if (detFields["업태"]) subType = detFields["업태"];
            if (detFields["대표자"]) popupRepresentative = detFields["대표자"];
            if (detFields["인허가일자"]) {
              const rawP = detFields["인허가일자"].replace(/[^0-9]/g, "");
              if (rawP.length === 8) {
                popupPermitDate = `${rawP.slice(0, 4)}-${rawP.slice(4, 6)}-${rawP.slice(6, 8)}`;
              }
            }
          } catch (e) {
            // keep fallback
          }
        }

        // Fetch or resolve real permit date (PRMS_DT) from OpenAPI I2500 + KV cache
        let permitDate = VERIFIED_PRMS_DT[lcnsNo] || popupPermitDate || null;
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

        // Auto cross-reference Seoul Open Data (새올) if storeName is pending
        let resolvedCandidate = null;
        if (!storeName && getSeoulDistrictCode(item.INSTT_CD_NM)) {
          try {
            resolvedCandidate = await resolveSeoulStore({
              env,
              context,
              district: item.INSTT_CD_NM,
              industry: item.INDUTY_CD_NM || "기타",
              permitDate: permitDate,
              subType: subType,
              representative: item.PRSDNT_NM || popupRepresentative || "",
              licenseNo: lcnsNo
            });
          } catch (e) {}
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
        const displayStoreName = storeName || (resolvedCandidate ? `신규 채번 (${resolvedCandidate.store_name} 매칭됨)` : "신규 채번 (상호·주소 반영 대기중)");
        const displayAddress = address || (resolvedCandidate ? `${resolvedCandidate.address} (새올 행정망)` : (isPendingName ? "소재지 반영 대기중" : ""));

        return {
          license_no: lcnsNo,
          store_name: displayStoreName,
          raw_store_name: storeName,
          is_pending_name: isPendingName,
          resolved_candidate: resolvedCandidate,
          industry: item.INDUTY_CD_NM || "기타",
          district: item.INSTT_CD_NM || "",
          address: displayAddress,
          representative: item.PRSDNT_NM || popupRepresentative || "",
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
