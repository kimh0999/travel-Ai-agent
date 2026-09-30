"""명백히 불가능한 일정 검증 (SPEC 9-2). 문제는 경고로 저장하고 화면에 알린다."""
from app.schemas.course import CourseOut, to_minutes

MAX_DAY_MINUTES = 14 * 60
MAX_STAY_MINUTES = 8 * 60
MAX_LEG_MINUTES = 5 * 60
SLACK_MINUTES = 15  # 시작 시각 사이 여유 허용치
BREAKFAST = (to_minutes("07:00"), to_minutes("10:00"))
LUNCH = (to_minutes("11:00"), to_minutes("14:30"))
DINNER = (to_minutes("17:00"), to_minutes("21:00"))


def _fmt(minutes: int) -> str:
    return f"{minutes // 60}시간 {minutes % 60}분" if minutes >= 60 else f"{minutes}분"


def validate_schedule(course: CourseOut, trip_days: int) -> list[str]:
    warnings: list[str] = []
    if len(course.days) != trip_days:
        warnings.append(f"여행 기간은 {trip_days}일인데 코스는 {len(course.days)}일로 구성되어 있어요.")
    for day in course.days:
        stay = sum(i.stay_minutes for i in day.items)
        travel = sum(i.travel_from_prev.minutes_estimate for i in day.items if i.travel_from_prev)
        total = stay + travel
        if total > MAX_DAY_MINUTES:
            warnings.append(f"{day.day_index}일차: 체류·이동 합계가 약 {_fmt(total)}으로 하루 일정으로 비현실적이에요.")
        for item in day.items:
            if item.stay_minutes > MAX_STAY_MINUTES:
                warnings.append(f"{day.day_index}일차 '{item.name}': 체류 {item.stay_minutes}분은 너무 길어요.")
            if item.travel_from_prev and item.travel_from_prev.minutes_estimate > MAX_LEG_MINUTES:
                warnings.append(f"{day.day_index}일차 '{item.name}': 이동 {item.travel_from_prev.minutes_estimate}분은 한 구간 이동으로 비현실적이에요.")
        for prev, item in zip(day.items, day.items[1:]):
            if not (prev.start_time and item.start_time):
                continue
            leg = item.travel_from_prev.minutes_estimate if item.travel_from_prev else 0
            ready = to_minutes(prev.start_time) + prev.stay_minutes + leg
            if ready > to_minutes(item.start_time) + SLACK_MINUTES:
                warnings.append(f"{day.day_index}일차 '{item.name}': 앞 일정 체류·이동을 더하면 {item.start_time}에 도착하기 어려워요.")
        meals = [i for i in day.items if i.kind == "meal"]
        if not meals:
            warnings.append(f"{day.day_index}일차에 식사 구간이 없어요.")
        for meal in meals:
            if meal.start_time and not any(lo <= to_minutes(meal.start_time) <= hi for lo, hi in (BREAKFAST, LUNCH, DINNER)):
                warnings.append(f"{day.day_index}일차 '{meal.name}': {meal.start_time}은 보통 식사 시간이 아니에요.")
    return warnings
