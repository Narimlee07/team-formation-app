# 팀 편성 웹 앱

## 1. 프로젝트 소개
학생들이 정해진 역할을 바탕으로 팀을 구성하고, 팀 지원 및 투표를 진행할 수 있는 웹 앱입니다.

## 2. 배포 주소
https://team-formation-app-bwfl4to4bvu4xtxdklvfeg.streamlit.app/

## 3. 사용 기술
- Python
- Streamlit
- Supabase
- OpenRouter
- GitHub

## 4. 주요 기능
- 학번과 비밀번호를 이용한 로그인
- 학생별 주 역할 및 보조 역할 표시
- 팀별 인원과 구성원 확인
- 팀 지원 및 팀원 투표
- 관리자 모집 마감
- AI를 이용한 미배정 학생 팀 편성
- 배정 결과 검증 및 확정

## 5. 실행 방법
1. 저장소를 내려받습니다.
2. 필요한 패키지를 설치합니다.
3. 환경변수를 설정합니다.
4. 다음 명령어로 앱을 실행합니다.

```bash
pip install -r requirements.txt
python -m streamlit run app_v7.py
```

## 6. 데이터베이스
- Supabase 사용
- 테이블 이름은 `tf_`로 시작합니다.
- 데이터베이스 구조는 `schema.sql`을 참고합니다.

## 7. 환경변수
- `DATABASE_URL`
- `OPENROUTER_API_KEY`
- `ADMIN_PASSWORD`
- `OPENROUTER_MODELS`

※ 비밀번호와 API 키 등 비밀 정보는 저장소에 올리지 않습니다.

## 8. 과제 추가 자료
- PRD 및 구현 계획: 추후 추가
- 쉬움·보통·어려움 구현 내용: 추후 추가
- AI 모델 3개 및 호출 결과: 추후 추가
- OpenRouter 실패 상황 증거: 추후
