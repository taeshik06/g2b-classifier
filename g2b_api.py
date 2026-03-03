"""
나라장터 오픈 API 호출 및 공고 분류 로직
"""

import io
import requests
import fitz  # PyMuPDF

G2B_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 유형별 목록 엔드포인트 — bidNtceNo + inqryDiv=2 로 단건 조회
LIST_ENDPOINTS = [
    f"{G2B_BASE}/getBidPblancListInfoCnstwk",   # 공사
    f"{G2B_BASE}/getBidPblancListInfoServc",    # 용역
    f"{G2B_BASE}/getBidPblancListInfoThng",     # 물품/제조
    f"{G2B_BASE}/getBidPblancListInfoFrgcpt",   # 외자
    f"{G2B_BASE}/getBidPblancListInfoEtc",      # 기타
]

# API 응답에서 텍스트로 추출할 필드 목록
TEXT_FIELDS = [
    "bidNtceNm",        # 공고명
    "ntceSpecCntn",     # 공고 특기사항 (있을 경우)
    "ntceInsttNm",      # 공고기관명
    "dminsttNm",        # 수요기관명
    "cntrctCnclsMthdNm",  # 계약체결방법명
]

# 금액 우선순위 필드 (API 실제 응답 기준)
AMOUNT_FIELDS = [
    "bdgtAmt",              # 예산금액
    "presmptPrce",          # 추정가격
    "asignBdgtAmt",         # 배정예산액
    "drwtPrceBsisAmt",      # 기초금액
]

# 첨부파일 URL/이름 필드 (ntceSpecDocUrl1~5, ntceSpecFileNm1~5)
MAX_ATTACH = 5


def _parse_bid_no(bid_no: str):
    """'R26BK01347086' 또는 'R26BK01347086-00' 형태 파싱"""
    bid_no = bid_no.strip()
    if "-" in bid_no:
        no, ord_ = bid_no.rsplit("-", 1)
        return no, ord_
    return bid_no, "00"


def get_bid_detail(api_key: str, bid_no: str) -> dict:
    """
    유형별 목록 엔드포인트를 순서대로 시도, bidNtceNo로 단건 필터링.
    성공하면 item dict, 실패하면 예외 발생.
    """
    no, ord_ = _parse_bid_no(bid_no)
    params = {
        "ServiceKey": api_key,  # 대문자 S
        "numOfRows": "10",
        "pageNo": "1",
        "inqryDiv": "2",        # 2 = 입찰공고번호로 조회 (1=등록일시, 3=변경일시)
        "bidNtceNo": no,
        "type": "json",
    }

    last_err = None
    for endpoint in LIST_ENDPOINTS:
        try:
            resp = requests.get(endpoint, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            body = data.get("response", {}).get("body", {})
            total = body.get("totalCount", 0)
            if not total or str(total) == "0":
                continue

            items = body.get("items")
            if not items:
                continue

            # JSON 응답: items 가 list 또는 {"item": [...]} 두 형태 모두 대응
            if isinstance(items, list):
                item = items
            elif isinstance(items, dict):
                item = items.get("item", [])
                if isinstance(item, dict):
                    item = [item]
            else:
                continue

            if item:
                result = item[0]
                result["_bid_no"] = no
                result["_bid_ord"] = ord_
                return result

        except Exception as e:
            last_err = e
            continue

    raise Exception(f"공고 조회 실패: {last_err or '데이터 없음'}")


def extract_pdf_urls(detail: dict) -> list:
    """
    API 응답 item에서 PDF 첨부파일 URL 목록 추출.
    ntceSpecFileNm1~5 / ntceSpecDocUrl1~5 쌍을 검사해 PDF만 반환.
    """
    pdf_urls = []
    for i in range(1, MAX_ATTACH + 1):
        name = detail.get(f"ntceSpecFileNm{i}", "") or ""
        url = detail.get(f"ntceSpecDocUrl{i}", "") or ""
        if not url:
            continue
        # HWP 제외, PDF 또는 이름 미확인(일단 시도) 허용
        if name.lower().endswith(".hwp") or name.lower().endswith(".hwpx"):
            continue
        if name.lower().endswith(".pdf") or not name:
            pdf_urls.append(url)
    return pdf_urls


def download_pdf_text(url: str) -> str:
    """URL에서 PDF 다운로드 후 텍스트 추출. 실패하면 빈 문자열."""
    if not url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        is_pdf = (
            "pdf" in content_type.lower()
            or url.lower().endswith(".pdf")
            or resp.content[:4] == b"%PDF"
        )
        if not is_pdf:
            return ""

        doc = fitz.open(stream=resp.content, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        return text
    except Exception:
        return ""


def check_keywords(text: str, rules: list) -> list:
    """
    키워드 규칙 적용.
    - AND : words 모두 포함
    - CONTAINS / OR : words 중 하나라도 포함
    매칭된 규칙 name 목록 반환.
    """
    matched = []
    for rule in rules:
        words = rule.get("words", [])
        name = rule.get("name", "")
        rule_type = rule.get("type", "CONTAINS")

        if rule_type == "AND":
            if all(w in text for w in words):
                matched.append(name)
        else:  # CONTAINS / OR
            if any(w in text for w in words):
                matched.append(name)
    return matched


def classify_amount(amount: float, ranges: list) -> str:
    """금액 구간 분류."""
    if amount <= 0:
        return "금액 미확인"
    for r in ranges:
        lo = r.get("min", 0)
        hi = r.get("max")
        if hi is None:
            if amount >= lo:
                return r["label"]
        else:
            if lo <= amount < hi:
                return r["label"]
    return "범위 외"


def classify_bid(api_key: str, bid_no: str, config: dict) -> dict:
    """
    공고 하나를 분류해서 결과 dict 반환.
    {
        bid_no, name, institution,
        amount, amount_label,
        is_special, special_tags,
        pdf_count,
        error
    }
    """
    result = {
        "bid_no": bid_no,
        "name": "",
        "institution": "",
        "amount": 0,
        "amount_label": "",
        "is_special": False,
        "special_tags": [],
        "pdf_count": 0,
        "error": None,
    }

    try:
        detail = get_bid_detail(api_key, bid_no)

        result["name"] = detail.get("bidNtceNm", "")
        result["institution"] = detail.get("ntceInsttNm", "")

        # 금액 추출
        for field in AMOUNT_FIELDS:
            raw = detail.get(field, "")
            if raw and str(raw).strip() not in ("", "0"):
                try:
                    result["amount"] = float(str(raw).replace(",", ""))
                    break
                except ValueError:
                    pass

        result["amount_label"] = classify_amount(
            result["amount"], config.get("amount_ranges", [])
        )

        # 텍스트 수집: API 필드
        text_parts = [str(detail.get(f, "") or "") for f in TEXT_FIELDS]

        # 텍스트 수집: 첨부 PDF (응답에 포함된 ntceSpecDocUrl 필드 사용)
        for url in extract_pdf_urls(detail):
            pdf_text = download_pdf_text(url)
            if pdf_text:
                text_parts.append(pdf_text)
                result["pdf_count"] += 1

        combined = "\n".join(text_parts)

        # 키워드 분류
        tags = check_keywords(combined, config.get("keywords", []))
        result["special_tags"] = tags
        result["is_special"] = bool(tags)

    except Exception as e:
        result["error"] = str(e)

    return result
