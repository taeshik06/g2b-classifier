"""
나라장터 오픈 API 호출 및 공고 분류 로직
"""

import requests
import fitz  # PyMuPDF

G2B_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 유형별 목록 엔드포인트 — bidNtceNo + inqryDiv=2 로 단건 조회
LIST_ENDPOINTS = [
    (f"{G2B_BASE}/getBidPblancListInfoCnstwk", "공사"),
    (f"{G2B_BASE}/getBidPblancListInfoServc",  "용역"),
    (f"{G2B_BASE}/getBidPblancListInfoThng",   "물품"),
    (f"{G2B_BASE}/getBidPblancListInfoFrgcpt", "외자"),
    (f"{G2B_BASE}/getBidPblancListInfoEtc",    "기타"),
]

# 유형별 기초금액 엔드포인트
BSSAMT_ENDPOINTS = {
    "공사": f"{G2B_BASE}/getBidPblancListInfoCnstwkBsisAmount",
    "용역": f"{G2B_BASE}/getBidPblancListInfoServcBsisAmount",
    "물품": f"{G2B_BASE}/getBidPblancListInfoThngBsisAmount",
}

A_VALUE_ENDPOINT = f"{G2B_BASE}/getBidPblancListBidPrceCalclAInfo"

# 텍스트 키워드 매칭에 사용할 API 필드
TEXT_FIELDS = [
    "bidNtceNm",
    "ntceSpecCntn",
    "ntceInsttNm",
    "dminsttNm",
    "cntrctCnclsMthdNm",
    "sucsfbidMthdNm",
]

MAX_ATTACH = 5


# ── 공통 헬퍼 ───────────────────────────────────────────────

def _parse_bid_no(bid_no: str):
    bid_no = bid_no.strip()
    if "-" in bid_no:
        no, ord_ = bid_no.rsplit("-", 1)
        return no, ord_
    return bid_no, "00"


def _to_float(val) -> float:
    if not val:
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _call_api(endpoint: str, params: dict) -> list:
    """API 호출 후 items 리스트 반환. 데이터 없으면 빈 리스트."""
    resp = requests.get(endpoint, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    body = data.get("response", {}).get("body", {})
    total = body.get("totalCount", 0)
    if not total or str(total) == "0":
        return []
    items = body.get("items")
    if not items:
        return []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        item = items.get("item", [])
        return [item] if isinstance(item, dict) else (item or [])
    return []


# ── API 조회 함수들 ─────────────────────────────────────────

def get_bid_detail(api_key: str, bid_no: str) -> dict:
    """공고 기본 정보 조회. 유형(공사/용역/물품…)을 _bid_type 에 저장."""
    no, ord_ = _parse_bid_no(bid_no)
    params = {
        "ServiceKey": api_key,
        "numOfRows": "10",
        "pageNo": "1",
        "inqryDiv": "2",
        "bidNtceNo": no,
        "type": "json",
    }
    last_err = None
    for endpoint, bid_type in LIST_ENDPOINTS:
        try:
            items = _call_api(endpoint, params)
            if items:
                result = items[0]
                result["_bid_no"]   = no
                result["_bid_ord"]  = ord_
                result["_bid_type"] = bid_type
                return result
        except Exception as e:
            last_err = e
    raise Exception(f"공고 조회 실패: {last_err or '데이터 없음'}")


def get_bssamt_info(api_key: str, bid_no: str, bid_type: str) -> dict:
    """기초금액 정보 조회. 실패하면 빈 dict."""
    endpoint = BSSAMT_ENDPOINTS.get(bid_type)
    if not endpoint:
        return {}
    params = {
        "ServiceKey": api_key,
        "numOfRows": "10",
        "pageNo": "1",
        "inqryDiv": "2",
        "bidNtceNo": bid_no,
        "type": "json",
    }
    try:
        items = _call_api(endpoint, params)
        return items[0] if items else {}
    except Exception:
        return {}


def get_a_value_info(api_key: str, bid_no: str) -> dict:
    """A값 구성항목 조회. 실패하면 빈 dict."""
    params = {
        "ServiceKey": api_key,
        "numOfRows": "10",
        "pageNo": "1",
        "inqryDiv": "2",
        "bidNtceNo": bid_no,
        "type": "json",
    }
    try:
        items = _call_api(A_VALUE_ENDPOINT, params)
        return items[0] if items else {}
    except Exception:
        return {}


def calc_a_value(a_info: dict) -> float:
    """
    A값 = 산업안전보건관리비 + 안전관리비 + 퇴직공제부금비
          + 국민건강보험료 + 국민연금보험료 + 노인장기요양보험료
          + 품질관리비 (qltyMngcstAObjYn=Y)
          + 표준시장단가금액 (smkpAmtYn=Y)
    """
    if not a_info:
        return 0.0
    total = (
        _to_float(a_info.get("sftyMngcst"))
        + _to_float(a_info.get("sftyChckMngcst"))
        + _to_float(a_info.get("rtrfundNon"))
        + _to_float(a_info.get("mrfnHealthInsrprm"))
        + _to_float(a_info.get("npnInsrprm"))
        + _to_float(a_info.get("odsnLngtrmrcprInsrprm"))
    )
    if a_info.get("qltyMngcstAObjYn") == "Y":
        total += _to_float(a_info.get("qltyMngcst"))
    if a_info.get("smkpAmtYn") == "Y":
        total += _to_float(a_info.get("smkpAmt"))
    return total


def classify_qual_criteria(sucsfbid_mthd_nm: str, full_text: str = "") -> str:
    """
    적격심사 기준 분류.
    sucsfbidMthdNm(낙찰방법명) 단독으로 판단하면 행정안전부 기준을 놓치는 경우가 있어
    PDF 포함 전체 텍스트(full_text)까지 함께 검색한다.

    행정안전부 기준 특징:
      - PDF 본문에 "행정안전부 예규", "지방자치단체 입찰시 낙찰자 결정 기준" 등이 명시됨
      - 낙찰방법명에는 그냥 "적격심사제-..." 만 들어있는 경우가 많음

    조달청 기준 특징:
      - 낙찰방법명에 "조달청"이 명시되는 경우가 많음
      - PDF에도 "조달청 적격심사 세부기준" 등이 등장
    """
    combined = (sucsfbid_mthd_nm or "") + "\n" + (full_text or "")

    # 행정안전부 기준 — PDF에 명시되는 표현들
    haean_keywords = [
        "행정안전부 예규",
        "행정안전부 기준",
        "지방자치단체 입찰시 낙찰자 결정",
        "지방자치단체입찰시낙찰자결정",
        "행정자치부 예규",          # 옛 명칭
        "행정자치부 기준",
    ]
    if any(k in combined for k in haean_keywords):
        return "행정안전부 기준"

    # 조달청 기준
    if "조달청" in combined:
        return "조달청 기준"

    # 적격심사는 맞는데 기관 불명확
    if "적격심사" in combined or "계약이행능력심사" in combined:
        return "기타 적격심사"

    return "해당없음"


# ── PDF ────────────────────────────────────────────────────

def extract_pdf_urls(detail: dict) -> list:
    pdf_urls = []
    for i in range(1, MAX_ATTACH + 1):
        name = detail.get(f"ntceSpecFileNm{i}", "") or ""
        url  = detail.get(f"ntceSpecDocUrl{i}", "") or ""
        if not url:
            continue
        if name.lower().endswith((".hwp", ".hwpx")):
            continue
        if name.lower().endswith(".pdf") or not name:
            pdf_urls.append(url)
    return pdf_urls


def download_pdf_text(url: str) -> str:
    if not url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        is_pdf = (
            "pdf" in resp.headers.get("content-type", "").lower()
            or url.lower().endswith(".pdf")
            or resp.content[:4] == b"%PDF"
        )
        if not is_pdf:
            return ""
        doc = fitz.open(stream=resp.content, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


# ── 키워드 분류 ─────────────────────────────────────────────

def check_keywords(text: str, rules: list) -> list:
    matched = []
    for rule in rules:
        words     = rule.get("words", [])
        name      = rule.get("name", "")
        rule_type = rule.get("type", "CONTAINS")
        if rule_type == "AND":
            if all(w in text for w in words):
                matched.append(name)
        else:
            if any(w in text for w in words):
                matched.append(name)
    return matched


# ── 메인 분류 함수 ──────────────────────────────────────────

def classify_bid(api_key: str, bid_no: str, config: dict) -> dict:
    """
    공고 하나를 분류해 결과 dict 반환.
    {
        bid_no, name, institution, bid_type,
        presmpt_prce,   # 추정가격
        bssamt,         # 기초금액
        lwlt_rate,      # 낙찰하한율 (%)
        a_value,        # A값 (0이면 미해당/미공개)
        pure_const_cost,# 순공사원가
        qual_criteria,  # 적격심사 기준
        is_special, special_tags,
        pdf_count, error
    }
    """
    result = {
        "bid_no": bid_no,
        "name": "",
        "institution": "",
        "bid_type": "",
        "presmpt_prce": 0.0,
        "bssamt": 0.0,
        "lwlt_rate": 0.0,
        "a_value": 0.0,
        "pure_const_cost": 0.0,
        "qual_criteria": "",
        "is_special": False,
        "special_tags": [],
        "pdf_count": 0,
        "error": None,
    }

    try:
        # ① 기본 공고 정보
        detail = get_bid_detail(api_key, bid_no)
        no        = detail["_bid_no"]
        bid_type  = detail["_bid_type"]

        result["name"]        = detail.get("bidNtceNm", "")
        result["institution"] = detail.get("ntceInsttNm", "")
        result["bid_type"]    = bid_type
        result["presmpt_prce"] = _to_float(detail.get("presmptPrce"))
        result["lwlt_rate"]   = _to_float(detail.get("sucsfbidLwltRate"))

        # ② 기초금액 / 순공사원가
        bss = get_bssamt_info(api_key, no, bid_type)
        result["bssamt"]          = _to_float(bss.get("bssamt"))
        result["pure_const_cost"] = _to_float(bss.get("bssAmtPurcnstcst"))

        # ③ A값 (공사 기초금액에 A값 적용 여부 확인 후)
        if bss.get("bidPrceCalclAYn") == "Y":
            a_info = get_a_value_info(api_key, no)
            result["a_value"] = calc_a_value(a_info)

        # ④ 텍스트 수집 (API 필드 + PDF)
        text_parts = [str(detail.get(f, "") or "") for f in TEXT_FIELDS]
        for url in extract_pdf_urls(detail):
            pdf_text = download_pdf_text(url)
            if pdf_text:
                text_parts.append(pdf_text)
                result["pdf_count"] += 1

        combined = "\n".join(text_parts)

        # ⑤ 적격심사 기준 — PDF 포함 전체 텍스트로 판단
        result["qual_criteria"] = classify_qual_criteria(
            detail.get("sucsfbidMthdNm", ""), combined
        )

        # ⑥ 특이 공고 키워드 분류
        tags = check_keywords(combined, config.get("keywords", []))
        result["special_tags"] = tags
        result["is_special"]   = bool(tags)

    except Exception as e:
        result["error"] = str(e)

    return result
