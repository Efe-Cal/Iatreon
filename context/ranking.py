import math

from .models import Article


class QualityRanker:
    STUDY_TYPE_SCORES = {
        "systematic review": 50,
        "meta-analysis": 50,
        "randomized controlled trial": 40,
        "rct": 40,
        "controlled clinical trial": 35,
        "clinical trial": 30,
        "cohort study": 25,
        "case-control study": 20,
        "observational study": 15,
        "case report": 5,
        "review": 10,
        "journal article": 10,
    }

    def score(self, article: Article) -> float:
        score = 0.0

        study_type_lower = (article.study_type or "").lower()
        for study_type, pts in self.STUDY_TYPE_SCORES.items():
            if study_type in study_type_lower:
                score += pts
                break
        else:
            score += 5

        if article.citation_count > 0:
            score += min(25, math.log10(article.citation_count + 1) * 10)

        current_year = 2026
        if article.year > 0:
            age = current_year - article.year
            if age <= 2:
                score += 15
            elif age <= 5:
                score += 10
            elif age <= 10:
                score += 5

        if article.full_text_available:
            score += 10

        return round(score, 2)

    def rank(self, articles: list[Article]) -> list[Article]:
        for article in articles:
            article.quality_score = self.score(article)
        return sorted(articles, key=lambda a: a.quality_score, reverse=True)