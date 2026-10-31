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

## 9. OpenRouter AI 모델 호출 실패 사례

1차 모델 호출 시 잘못된 모델 식별자를 사용하여 HTTP 400 오류가 발생했다. 앱은 오류를 확인한 뒤 2차 모델인 `nvidia/nemotron-3.5-lightning:free`로 자동 전환했다. 2차 모델은 배정안을 생성했고, 앱의 5가지 검증을 모두 통과했다.

- 실패 및 자동 전환 증거: img/ai-model-failure.png
- 3개 모델 개별 호출 성공 증거: img/openrouter_3models_success.png

※ 첫 번째 시험은 실제 서비스 장애가 아니라, 1차 모델 실패 후 다음 모델로 넘어가는 기능을 확인하기 위해 의도적으로 잘못된 모델 식별자를 사용한 시험이다.

## 6. Claude의 잘못된 판단 사례

Claude에게 팀 구성 앱의 테스트 시나리오 작성을 요청했을 때, 실제 사용 중인 `어려움_1.csv`가 아닌 `쉬움.csv`를 기준으로 학생 번호와 테스트 시나리오를 안내하는 오류가 있었다.

파일을 다시 확인해 달라고 요청한 결과, Claude는 처음 안내가 잘못되었음을 인정하고 `어려움_1.csv` 기준으로 내용을 수정했다.

이를 통해 AI가 파일을 잘못 이해하거나 다른 자료를 기준으로 답변할 수 있으므로, 실제 사용 파일과 대조하여 결과를 확인해야 한다는 점을 알게 되었다.

- 증거 화면: img/claude-wrong-answer.png
