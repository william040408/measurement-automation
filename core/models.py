from dataclasses import dataclass
from abc import ABC, abstractmethod

# =========================================================
# Base Class
# =========================================================

@dataclass
class Measurement(ABC):
    """
    모든 측정의 공통 부모 클래스
    """
    name: str
    cat: str = ""
    dv: float = 0.0
    
    @abstractmethod
    def classify(self) -> str:
        """
        OK / UN / UP / NG 판정
        """
        pass

    def is_ng(self) -> bool:
        return self.classify() == "NG"

    def is_ok(self) -> bool:
        return self.classify() == "OK"

    @abstractmethod
    def summary(self) -> str:
        """
        핵심 수치 요약 출력
        """
        pass


# =========================================================
# Nominal-based Measurement (직경, 거리, 위치 등)
# =========================================================

@dataclass
class NominalMeasurement(Measurement):
    nv: float = 0.0
    ut: float = 0.0
    lt: float = 0.0
    up_limit: float = 0.0
    lo_limit: float = 0.0

    def __post_init__(self):
        # 객체가 만들어지자마자 NV + UT, NV + LT를 계산해서 저장합니다.
        self.up_limit = self.nv + self.ut
        self.lo_limit = self.nv + self.lt

    @property
    def actual_value(self) -> float:
        return self.nv + self.dv
    
    def standard_value(self) -> float:
        return self.nv

    def classify(self) -> str:
        from config import classify_settings as cs

        # UT=0, LT=0 → PDF에서 공차 파싱 불가 → 판정 스킵
        if self.ut == 0.0 and self.lt == 0.0:
            return "OK"

        if self.dv > self.ut or self.dv < self.lt:
            return "NG"

        def _warn(margin, ratio):
            if cs.MODE == "OR":
                return margin <= cs.MARGIN_LIMIT or ratio >= cs.RATIO_LIMIT
            elif cs.MODE == "AND":
                return margin <= cs.MARGIN_LIMIT and ratio >= cs.RATIO_LIMIT
            elif cs.MODE == "MARGIN_ONLY":
                return margin <= cs.MARGIN_LIMIT
            else:  # RATIO_ONLY
                return ratio >= cs.RATIO_LIMIT

        # 상한 경계: UT와의 거리 (UT=0이어도 체크)
        m_up = self.ut - self.dv
        r_up = (self.dv / self.ut) if self.ut != 0 else 0.0
        if _warn(m_up, r_up):
            return "UP"

        # 하한 경계: LT와의 거리 (LT=0이어도 체크)
        m_lo = self.dv - self.lt
        r_lo = (self.dv / self.lt) if self.lt != 0 else 0.0
        if _warn(m_lo, r_lo):
            return "UN"

        return "OK"

    def actual(self) -> float:
        return self.nv + self.dv

    def summary(self) -> str:
        return (
            f"[{self.classify():^4}] {self.cat:<8} | {self.name}\n"
            f"       NV: {self.nv:.3f} | UT: {self.ut:.3f} | LT: {self.lt:.3f}\n"
            f"       AV: {self.actual():.3f} | DV: {self.dv:.3f}"
        )


# =========================================================
# Tolerance-only Measurement (진원도, 흔들림 등)
# =========================================================

@dataclass
class ToleranceMeasurement(Measurement):
    to: float = 0.0
    up_limit: float = 0.0
    lo_limit: float = 0.0

    def __post_init__(self):
        # 흔들림 등은 공차값(to) 자체가 상한선이고, 하한선은 0입니다.
        self.up_limit = self.to
        self.lo_limit = 0.0

    @property
    def actual_value(self) -> float:
        return self.dv
    
    def standard_value(self) -> float:
        return self.to

    def classify(self) -> str:
        if self.to <= 0:
            return "NG" if self.dv > 0 else "OK"
        ratio = abs(self.dv) / self.to
        return "NG" if ratio > 1.0 else "OK"

    def summary(self) -> str:
        return (
            f"[{self.classify():^4}] {self.cat:<8} | {self.name}\n"
            f"       TO: {self.to:.3f} | DV: {self.dv:.3f}"
        )


# =========================================================
# Section Marker (PDF 섹션 구분선 — 수치 데이터 아님)
# =========================================================

@dataclass
class SectionMarker:
    """
    PDF의 '--- 섹션이름 ---' 구분선을 나타내는 마커.
    파싱 결과 리스트에 포함되어 측정 항목 간 경계를 명확히 함.
    signature 비교나 수치 연산에는 사용되지 않음.
    """
    name: str