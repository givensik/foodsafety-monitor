// Cloudflare Pages Function: /api/ledger?no=2026001000413418
export async function onRequestGet(context) {
  const { request } = context;
  const reqUrl = new URL(request.url);
  const ledgerNo = (reqUrl.searchParams.get("no") || "").trim();

  if (!/^\d{16}$/.test(ledgerNo)) {
    return new Response(JSON.stringify({
      success: false,
      error: "16자리 숫자 형태의 대장번호(BSN_LCNS_LEDG_NO)를 입력해 주세요. (예: 2026001000413418)"
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

    const detRes = await fetch(`${DETAIL_URL}?bsnLcnsLedgNo=${ledgerNo}&callPage=${callPage}`, {
      headers: {
        ...commonHeaders,
        "Referer": MAIN_PAGE_URL,
        "Cookie": cookieStr
      }
    });
    const detHtml = await detRes.text();

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

    return new Response(JSON.stringify({
      success: true,
      ledger_no: ledgerNo,
      exists: true,
      is_pending_name: isPendingName,
      checked_at: new Date().toISOString(),
      data: {
        store_name: storeName || "신규 채번 (상호·주소 반영 대기중)",
        raw_store_name: storeName,
        industry: fields["영업 인허가 종류"] || "-",
        license_no: lcnsNo || "-",
        address: fields["소재지"] || "",
        phone: fields["전화번호"] || "-",
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
