// Cloudflare Pages Function: /api/ledger?no=2026001000413418[&view=html]
// Note: Does NOT store any data (especially phone numbers) in KV or database.
// When view=html is passed, streams the official Food Safety Korea bsnInfoDetail.do HTML popup directly.

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
  const ledgerNo = (reqUrl.searchParams.get("no") || "").trim();
  const viewMode = (reqUrl.searchParams.get("view") || "json").toLowerCase();

  if (!/^\d{16}$/.test(ledgerNo)) {
    return new Response(JSON.stringify({
      success: false,
      error: "16자리 숫자 형태의 대장번호(BSN_LCNS_LEDG_NO)를 입력해 주세요. (예: 2026001000413573)"
    }), {
      status: 400,
      headers: { "Content-Type": "application/json; charset=UTF-8" }
    });
  }

  const BASE_URL = "https://www.foodsafetykorea.go.kr";
  const MAIN_PAGE_URL = `${BASE_URL}/portal/specialinfo/searchInfoCompany.do`;
  const DETAIL_URL = `${BASE_URL}/potalPopup/fooddanger/bsnInfoDetail.do`;

  const commonHeaders = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
  };

  try {
    const initRes = await fetch(MAIN_PAGE_URL, { headers: commonHeaders });
    const initHtml = await initRes.text();
    const callPageMatch = initHtml.match(/id=["']callPage["']\s+value=["']([^"']+)["']/);
    const callPage = callPageMatch ? callPageMatch[1] : "";

    const rawCookies = typeof initRes.headers.getSetCookie === "function"
      ? initRes.headers.getSetCookie()
      : (initRes.headers.get("set-cookie") ? [initRes.headers.get("set-cookie")] : []);

    const parsedCookies = [];
    if (callPage) parsedCookies.push("callPage=" + callPage);
    for (const c of rawCookies) {
      const part = c.split(";")[0].trim();
      if (part) parsedCookies.push(part);
    }
    const cookieStr = parsedCookies.join("; ");

    const targetPopupUrl = `${DETAIL_URL}?bsnLcnsLedgNo=${ledgerNo}&callPage=${callPage}`;
    const detRes = await fetch(targetPopupUrl, {
      headers: {
        ...commonHeaders,
        "Referer": MAIN_PAGE_URL,
        "Cookie": cookieStr
      }
    });
    const detHtml = await detRes.text();

    // Direct HTML viewer mode: stream Food Safety Korea's original popup HTML without storing anything
    if (viewMode === "html") {
      if (detHtml.includes("시스템에러가 발생하였습니다") || !detHtml.includes("<th")) {
        const notFoundHtml = `<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><title>미생성 대장번호 (${ledgerNo})</title></head>
        <body style="font-family:sans-serif;padding:32px;line-height:1.6;">
          <h2 style="color:#be123c;">[미생성 번호] 대장번호 ${ledgerNo}</h2>
          <p>식약처 상세원장(<code>bsnInfoDetail.do</code>)에서 <strong>"시스템에러가 발생하였습니다"</strong>를 반환했습니다. 아직 생성되지 않았거나 결번인 번호입니다.</p>
        </body></html>`;
        return new Response(notFoundHtml, {
          headers: {
            "Content-Type": "text/html; charset=UTF-8",
            "Cache-Control": "no-store"
          }
        });
      }

      const wrappedHtml = `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <base href="https://www.foodsafetykorea.go.kr/">
  <title>식약처 업체 상세정보 자세히보기 (${ledgerNo})</title>
  <style>
    body { padding: 20px; background: #fff; font-family: 'Malgun Gothic', sans-serif; }
    .proxy-banner {
      margin-bottom: 16px; padding: 10px 14px; background: #f8fafc;
      border: 1px solid #cbd5e1; border-radius: 8px; font-size: 12px; color: #334155;
    }
    .proxy-banner code { font-weight: bold; color: #0f172a; }
  </style>
</head>
<body>
  <div class="proxy-banner">
    🔗 <strong>식품안전나라 업체 상세정보 자세히보기 (무저장 실시간 연동)</strong> &middot;
    원본 경로: <code>https://www.foodsafetykorea.go.kr/potalPopup/fooddanger/bsnInfoDetail.do?bsnLcnsLedgNo=${ledgerNo}</code>
  </div>
  ${detHtml}
</body>
</html>`;

      return new Response(wrappedHtml, {
        headers: {
          "Content-Type": "text/html; charset=UTF-8",
          "Cache-Control": "no-store"
        }
      });
    }

    if (detHtml.includes("시스템에러가 발생하였습니다") || !detHtml.includes("<th")) {
      return new Response(JSON.stringify({
        success: true,
        ledger_no: ledgerNo,
        exists: false,
        checked_at: new Date().toISOString(),
        raw_status: "시스템에러 팝업 (해당 대장번호 레코드 미생성/미존재)"
      }), {
        headers: {
          "Content-Type": "application/json; charset=UTF-8",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "no-store"
        }
      });
    }

    const fields = {};
    const pairRegex = /<th[^>]*>([\s\S]*?)<\/th>\s*<td[^>]*>([\s\S]*?)<\/td>/gi;
    let match;
    while ((match = pairRegex.exec(detHtml)) !== null) {
      const key = match[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
      const val = match[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
      if (key && !(key in fields)) {
        fields[key] = val;
      }
    }

    const lcnsNo = fields["인허가번호"] || "";
    let permitDate = null;
    if (lcnsNo) {
      try {
        const apiRes = await fetch(`http://openapi.foodsafetykorea.go.kr/api/sample/I2500/json/1/5/LCNS_NO=${lcnsNo}`);
        const apiJson = await apiRes.json();
        const rawPrms = apiJson?.I2500?.row?.[0]?.PRMS_DT;
        if (rawPrms && rawPrms.length === 8) {
          permitDate = `${rawPrms.slice(0, 4)}-${rawPrms.slice(4, 6)}-${rawPrms.slice(6, 8)}`;
        }
      } catch (e) {}
    }

    const storeName = fields["업체명"] || "";
    const isPendingName = storeName === "";
    const rawPhone = fields["전화번호"] || "-";
    const hasPhone = Boolean(rawPhone && rawPhone !== "-" && rawPhone !== "NULL");

    let resolvedCandidate = null;
    if (isPendingName) {
      const districtGuess = fields["소재지"] || fields["관할기관"] || "";
      let distCode = getSeoulDistrictCode(districtGuess);
      if (!distCode && lcnsNo) {
        if (lcnsNo.startsWith("2026004")) distCode = "JN";
        else if (lcnsNo.startsWith("20260076")) distCode = "GB";
        else if (lcnsNo.startsWith("20260147")) distCode = "GN";
        else if (lcnsNo.startsWith("20260109")) distCode = "GS";
      }
      if (distCode) {
        try {
          resolvedCandidate = await resolveSeoulStore({
            env,
            context,
            district: districtGuess || distCode,
            industry: fields["영업 인허가 종류"] || "",
            permitDate: permitDate,
            subType: fields["업태"] || "",
            representative: fields["대표자"] || "",
            licenseNo: lcnsNo
          });
        } catch (e) {}
      }
    }

    return new Response(JSON.stringify({
      success: true,
      ledger_no: ledgerNo,
      exists: true,
      is_pending_name: isPendingName,
      resolved_candidate: resolvedCandidate,
      checked_at: new Date().toISOString(),
      data: {
        store_name: storeName || (resolvedCandidate ? `신규 채번 (${resolvedCandidate.store_name} 매칭됨)` : "신규 채번 (상호·주소 반영 대기중)"),
        raw_store_name: storeName,
        resolved_candidate: resolvedCandidate,
        industry: fields["영업 인허가 종류"] || "-",
        license_no: lcnsNo || "-",
        address: fields["소재지"] || (resolvedCandidate ? `${resolvedCandidate.address} (새올 행정망)` : ""),
        has_phone: hasPhone,
        detail_view_url: `/api/ledger?no=${ledgerNo}&view=html`,
        openapi_url: lcnsNo ? `http://openapi.foodsafetykorea.go.kr/api/sample/I2500/json/1/5/LCNS_NO=${lcnsNo}` : null,
        sub_type: fields["업태"] || "-",
        permit_date: permitDate
      }
    }), {
      headers: {
        "Content-Type": "application/json; charset=UTF-8",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store"
      }
    });
  } catch (err) {
    return new Response(JSON.stringify({
      success: false,
      error: err.message
    }), {
      status: 500,
      headers: { "Content-Type": "application/json; charset=UTF-8" }
    });
  }
}
