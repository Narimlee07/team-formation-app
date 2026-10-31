"""
팀 편성 웹 앱 - 7단계: 모집 마감, AI 배정, 배정 확정 (app_v7.py)

이 단계에서 하는 일
  1) 제목과 안내 문구를 보여 준다.
  2) DATABASE_URL 로 Supabase DB에 연결한다.
     연결은 "연결 모음(풀)"에 한 번만 만들어 두고, 필요할 때 빌려 쓰고 돌려준다.
  3) schema.sql 의 tf_ 테이블 7개가 DB에 있는지 확인한다.
  4) 관리자 계정(학번 admin)을 준비한다. 비밀번호는 ADMIN_PASSWORD 값을 쓴다.
  5) 학번과 비밀번호로 로그인한다. 비밀번호는 bcrypt 로 검증한다.
  6) 로그인한 사람의 이름, 학번, 역할을 보여 주고 학생과 관리자를 구분한다.
  7) 로그아웃한다.
  8) 관리자만 명단 CSV 와 팀 수를 올려서 처음 상태를 만든다.
     - 학생 계정을 만들고(초기 비밀번호 1234, bcrypt 해시), 주 역할과 보조 역할을 저장한다.
     - 지원, 투표, 팀원, 마감 표시를 지우고 빈 팀(팀1, 팀2, ...)을 만든다. (과제 공고 2.6절)
     - 한 번의 트랜잭션으로 처리해서, 중간에 실패하면 이전 상태가 그대로 남는다.
  9) 학생 화면에 팀 목록을 보여 준다. (팀 이름, 팀원 이름, 주 역할, 보조 역할, 인원/정원)
     빈 팀도 보여 주고, 내 팀은 "(내 팀)"으로 구별한다. 관리자 화면에는 보이지 않는다.
 10) 학생이 팀에 지원한다. 지원할 때 규칙(마감, 이미 팀, 대기 중인 지원, 정원, 같은 주 역할,
     필수 포함 역할 자리)을 검사해서 어기면 "막힘"으로 접수하지 않는다. (과제 공고 2.4절, 3장 어려운 해결)
     빈 팀에 지원하면 바로 승인한다.
 11) 팀원이 지원에 찬성 또는 거부로 투표한다. 한 명이라도 거부하면 바로 거절하고,
     모두 찬성하면 승인 직전에 규칙을 다시 검사한 뒤 승인(또는 거절)한다.
     지원, 투표, 팀원은 모두 DB에 저장하고, 한 번의 동작은 하나의 트랜잭션으로 처리한다.
 12) 다른 사람의 변경을 보려면 "새로 고침" 단추를 누른다. (공고 3장 쉬운 해결, key 는 refresh)

 13) 관리자가 "모집 마감"(admin_close)을 누른다. 그 뒤로는 지원과 투표를 할 수 없다.
     대기 중이던 지원은 거절되고, 1명뿐인 팀의 학생은 팀에서 빠져 "팀이 없는 학생"이 된다. (공고 2.5절)
 14) 관리자가 "AI 배정"(admin_assign)을 누르면 팀이 없는 학생만 팀에 넣는다. (이미 팀에 있는 학생은 옮기지 않는다)
     OpenRouter 모델 3개를 1차, 2차, 3차 순서로 부르고(모델마다 전체 대기 120초),
     모두 실패하면 앱이 스스로(완전탐색) 배정한다. 진행 안내는 key 가 assign_status 인 칸에 보여 준다.
 15) 배정안은 5가지(빠짐없이 배정, 한 학생 한 팀, 팀당 2~4명, 주 역할 중복 없음, 필수 포함 역할)를
     통과한 것만 보여 준다. 규칙을 지키는 배정이 없으면 이유를 보여 주고 AI 를 부르지 않는다.
 16) 관리자가 "배정안 확정"(admin_confirm)을 누르면 다시 검사한 뒤 DB 에 저장한다.

  (이 파일은 app (3).py 에 위 기능을 더한 것이다. 기존 기능은 지우지 않았다.)
  - 학생의 회원가입과 역할 변경 기능은 만들지 않는다. (과제 공고에 없음)
     역할은 관리자가 올리는 명단 CSV 로만 정해진다.

비밀 값(DB 주소, 키, 비밀번호)은 코드에 적지 않는다.
  - 내 컴퓨터: .env 파일에서 읽는다.
  - 배포한 앱: Streamlit Secrets 에서 읽는다.
"""

import concurrent.futures
import csv
import io
import json
import os
import re
import time

import bcrypt
import psycopg2
import psycopg2.pool
from psycopg2.extras import execute_values
import streamlit as st
from dotenv import load_dotenv

try:
    import requests  # OpenRouter 호출에 쓴다. (streamlit 을 설치하면 함께 설치된다)
except ImportError:  # 없어도 앱은 켜지고, AI 호출만 실패로 처리한다.
    requests = None

# 화면 설정은 Streamlit 명령 중 가장 먼저, 딱 한 번 실행해야 한다.
st.set_page_config(page_title="팀 편성 웹 앱")

# 내 컴퓨터의 .env 파일을 읽는다. (배포 환경에는 .env 가 없으므로 아무 일도 안 한다)
load_dotenv()

# schema.sql 에서 만든 테이블 7개
EXPECTED_TABLES = [
    "tf_students",
    "tf_student_sub_roles",
    "tf_teams",
    "tf_members",
    "tf_applications",
    "tf_votes",
    "tf_settings",
]

# 관리자 계정의 학번과 이름
ADMIN_STUDENT_NO = "admin"
ADMIN_NAME = "관리자"

# 연결 모음에 동시에 열어 둘 수 있는 연결의 최대 개수
POOL_MAX_CONNECTIONS = 10

# 역할 6개 (schema.sql 의 허용 목록과 같아야 한다)
ROLES = [
    "기획자",
    "웹 프로그래머",
    "프론트엔드 디자이너",
    "테스터",
    "보고서 작성자",
    "발표자",
]

# 명단 CSV 의 열 이름
REQUIRED_COLUMNS = ["student_no", "name", "main_role", "sub_roles"]

# 보조 역할은 학생마다 0~2개
MAX_SUB_ROLES = 2

# 학생의 초기 비밀번호 (과제 공고 2.2절이 정한 값이며 비밀 값이 아니다)
INITIAL_PASSWORD = "1234"

# tf_settings 에서 "모집 마감 여부"를 저장할 때 쓸 이름 (명단을 올리면 지운다)
SETTING_CLOSED_KEY = "recruitment_closed"

# 오류가 많을 때 화면에 보여 줄 최대 개수
MAX_SHOWN_ERRORS = 20

# 한 팀의 정원 (과제 공고 2.3절. schema.sql 의 slot_no 는 1~4)
TEAM_MAX_SIZE = 4


class DatabaseUrlMissing(Exception):
    """DATABASE_URL 값을 찾지 못했을 때 쓰는 오류"""


class AdminPasswordMissing(Exception):
    """ADMIN_PASSWORD 값을 찾지 못했을 때 쓰는 오류"""


class NotAdmin(Exception):
    """관리자가 아닌 사람이 관리자 기능을 쓰려고 할 때 쓰는 오류"""


class NoFreeSlot(Exception):
    """팀에 빈 자리가 없는데 팀원을 넣으려 할 때 쓰는 오류 (규칙 검사를 통과했다면 생기지 않는다)"""


# ---------------------------------------------------------------------
# 비밀 값 읽기
# ---------------------------------------------------------------------
def get_secret(name):
    """비밀 값을 찾아서 돌려준다. 없으면 None."""
    # 1) 환경변수 (.env 를 읽었다면 여기에 들어 있다)
    value = os.getenv(name)

    # 2) 없으면 Streamlit Secrets (배포한 앱)
    if not value:
        try:
            value = st.secrets.get(name)
        except Exception:
            value = None

    return str(value) if value else None


def get_database_url():
    """DATABASE_URL 을 찾아서 돌려준다. 앞뒤 공백은 지운다."""
    url = get_secret("DATABASE_URL")
    return url.strip() if url else None


# ---------------------------------------------------------------------
# 데이터베이스 연결 (연결 모음)
# ---------------------------------------------------------------------
@st.cache_resource(show_spinner="데이터베이스에 연결하는 중...")
def get_pool():
    """연결 모음을 한 번만 만들어 계속 다시 쓴다."""
    url = get_database_url()
    if not url:
        raise DatabaseUrlMissing()

    # 10초 안에 연결되지 않으면 포기한다.
    return psycopg2.pool.ThreadedConnectionPool(
        1, POOL_MAX_CONNECTIONS, url, connect_timeout=10
    )


def run_db(action):
    """
    action(conn) 을 실행하고 결과를 돌려준다.

    - 끝까지 잘 되면 저장(commit)한다.
    - 중간에 오류가 나면 되돌린다(rollback). 여러 문장을 실행하다 실패해도 반쪽만 저장되지 않는다.
    - 연결이 끊겨 있었다면 그 연결을 버리고 새 연결로 한 번 더 시도한다.
    """
    db_pool = get_pool()

    for attempt in (1, 2):
        conn = db_pool.getconn()
        broken = False
        try:
            result = action(conn)
            conn.commit()
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True  # 이 연결은 쓸 수 없으니 버린다.
            if attempt == 2:
                raise
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.putconn(conn, close=broken)


def find_missing_tables(conn):
    """EXPECTED_TABLES 중에서 DB에 없는 테이블 이름 목록을 돌려준다."""
    with conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' and table_name = any(%s)",
            (EXPECTED_TABLES,),
        )
        found = {row[0] for row in cur.fetchall()}
    return [name for name in EXPECTED_TABLES if name not in found]


@st.cache_data(ttl=60, show_spinner=False)
def check_tables():
    """없는 테이블 목록을 구한다. 화면을 다시 그릴 때마다 묻지 않도록 60초 동안 기억한다."""
    return run_db(find_missing_tables)


# ---------------------------------------------------------------------
# 비밀번호 (bcrypt)
# ---------------------------------------------------------------------
def hash_password(password):
    """비밀번호를 해시(되돌릴 수 없는 문자열)로 바꾼다."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    """입력한 비밀번호가 저장된 해시와 맞으면 True."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 해시가 올바른 모양이 아니거나, 비밀번호가 너무 길면 "틀림"으로 처리한다.
        return False


# ---------------------------------------------------------------------
# 관리자 계정 준비
# ---------------------------------------------------------------------
def ensure_admin_account(conn):
    """학번 admin 계정을 만들거나, 비밀번호가 ADMIN_PASSWORD 와 다르면 갱신한다."""
    admin_password = get_secret("ADMIN_PASSWORD")
    if not admin_password:
        raise AdminPasswordMissing()

    with conn.cursor() as cur:
        cur.execute(
            "select password_hash, is_admin from tf_students where student_no = %s",
            (ADMIN_STUDENT_NO,),
        )
        row = cur.fetchone()

        # 이미 같은 비밀번호의 관리자 계정이 있으면 아무것도 바꾸지 않는다.
        if row and row[1] and verify_password(admin_password, row[0]):
            return

        cur.execute(
            "insert into tf_students (student_no, name, main_role, password_hash, is_admin) "
            "values (%s, %s, null, %s, true) "
            "on conflict (student_no) do update "
            "set password_hash = excluded.password_hash, is_admin = true",
            (ADMIN_STUDENT_NO, ADMIN_NAME, hash_password(admin_password)),
        )


@st.cache_resource(show_spinner=False)
def prepare_admin_account():
    """관리자 계정 준비를 앱이 켜진 뒤 한 번만 한다. (오류가 나면 저장하지 않고 다음에 다시 시도)"""
    run_db(ensure_admin_account)
    return True


# ---------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------
def password_is_correct(conn, student_no, password):
    """학번이 있고 비밀번호가 맞으면 True. (비밀번호 해시는 이 함수 밖으로 나가지 않는다)"""
    with conn.cursor() as cur:
        cur.execute(
            "select password_hash from tf_students where student_no = %s",
            (student_no,),
        )
        row = cur.fetchone()

    if row is None:
        return False
    return verify_password(password, row[0])


def load_profile(conn, student_no):
    """학번으로 계정 정보(이름, 주 역할, 보조 역할, 관리자 여부)를 읽는다. 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select s.id, s.student_no, s.name, s.main_role, s.is_admin,
                   coalesce(
                       array_agg(r.role order by r.role) filter (where r.role is not null),
                       '{}'
                   )
            from tf_students s
            left join tf_student_sub_roles r on r.student_id = s.id
            where s.student_no = %s
            group by s.id
            """,
            (student_no,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    # 비밀번호 해시는 일부러 담지 않는다.
    return {
        "id": row[0],
        "student_no": row[1],
        "name": row[2],
        "main_role": row[3],
        "is_admin": row[4],
        "sub_roles": list(row[5]),
    }


def handle_login(student_no, password):
    """로그인을 시도하고 (성공 여부, 안내 문구) 를 돌려준다."""
    student_no = student_no.strip()

    if not student_no or not password:
        return False, "막힘: 학번과 비밀번호를 모두 입력하세요."

    try:
        ok = run_db(lambda conn: password_is_correct(conn, student_no, password))
    except psycopg2.Error:
        return False, "막힘: 데이터베이스 문제로 로그인하지 못했습니다. 잠시 뒤 다시 시도하세요."

    if not ok:
        # 학번이 틀렸는지 비밀번호가 틀렸는지는 일부러 구분하지 않는다.
        return False, "막힘: 학번 또는 비밀번호가 틀렸습니다."

    return True, "승인: 로그인했습니다."


# ---------------------------------------------------------------------
# 명단(CSV) 올리기 - 관리자 전용
# ---------------------------------------------------------------------
def parse_roster_csv(raw):
    """
    CSV 파일의 내용(bytes)을 읽고 검사한다.
    (학생 목록, 오류 목록) 을 돌려준다. 오류가 하나라도 있으면 학생 목록은 비어 있다.
    이 함수는 DB를 건드리지 않는다.
    """
    try:
        text = raw.decode("utf-8-sig")  # BOM 이 있어도 없어도 읽는다.
    except UnicodeDecodeError:
        return [], [
            "파일을 읽을 수 없음: UTF-8 형식의 CSV 파일이 아닙니다. "
            "엑셀에서 'CSV UTF-8' 형식으로 저장해 보세요."
        ]

    reader = csv.reader(io.StringIO(text, newline=""))
    students = []
    errors = []
    first_line_of = {}  # 학번 -> 처음 나온 줄 번호 (중복 검사용)

    try:
        # 첫 줄: 열 이름
        try:
            header_row = next(reader)
        except StopIteration:
            return [], ["파일이 비어 있음: 첫 줄에 열 이름이 있어야 합니다."]

        header = [cell.strip() for cell in header_row]
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        unknown = [name or "(이름 없는 열)" for name in header if name not in REQUIRED_COLUMNS]
        repeated = sorted({name for name in header if header.count(name) > 1})

        if missing:
            errors.append("1행(열 이름): 없는 열이 있음 - " + ", ".join(missing))
        if unknown:
            errors.append("1행(열 이름): 알 수 없는 열 이름이 있음 - " + ", ".join(unknown))
        if repeated:
            errors.append("1행(열 이름): 같은 열 이름이 두 번 나옴 - " + ", ".join(repeated))
        if errors:
            errors.append("열 이름은 " + ", ".join(REQUIRED_COLUMNS) + " 이어야 합니다.")
            return [], errors

        # 둘째 줄부터: 학생
        for row in reader:
            line_no = reader.line_num
            if not any(cell.strip() for cell in row):
                continue  # 빈 줄은 건너뛴다.

            if len(row) != len(header):
                errors.append(
                    f"{line_no}행: 열 개수가 맞지 않음 ({len(header)}개여야 하는데 {len(row)}개임). "
                    "쉼표를 지우거나 더 넣지 않았는지 확인하세요. "
                    "sub_roles 가 비어 있어도 마지막 쉼표는 있어야 합니다."
                )
                continue

            values = {name: cell.strip() for name, cell in zip(header, row)}
            student_no = values["student_no"]
            name = values["name"]
            main_role = values["main_role"]
            row_errors = []

            if not student_no:
                row_errors.append("student_no(학번)가 비어 있음")
            elif student_no == ADMIN_STUDENT_NO:
                row_errors.append(f"학번 '{ADMIN_STUDENT_NO}'은 관리자 계정이 쓰므로 학생에게 쓸 수 없음")
            elif student_no in first_line_of:
                row_errors.append(f"학번 '{student_no}'이(가) {first_line_of[student_no]}행과 중복됨")
            else:
                first_line_of[student_no] = line_no

            if not name:
                row_errors.append("name(이름)이 비어 있음")

            if not main_role:
                row_errors.append("main_role(주 역할)이 비어 있음")
            elif main_role not in ROLES:
                row_errors.append(f"main_role(주 역할) '{main_role}'은(는) 없는 역할임")

            # 보조 역할: 세미콜론(;)으로 구분하고, 비어 있어도 된다.
            sub_roles = [role.strip() for role in values["sub_roles"].split(";") if role.strip()]
            unknown_roles = [role for role in sub_roles if role not in ROLES]
            if unknown_roles:
                row_errors.append("sub_roles(보조 역할)에 없는 역할이 있음 - " + ", ".join(unknown_roles))
            if len(sub_roles) > MAX_SUB_ROLES:
                row_errors.append(f"보조 역할은 {MAX_SUB_ROLES}개까지인데 {len(sub_roles)}개임")
            if len(set(sub_roles)) != len(sub_roles):
                row_errors.append("sub_roles(보조 역할)에 같은 역할이 두 번 들어 있음")

            if row_errors:
                errors.append(f"{line_no}행: " + " / ".join(row_errors))
            else:
                students.append(
                    {
                        "student_no": student_no,
                        "name": name,
                        "main_role": main_role,
                        "sub_roles": sub_roles,
                    }
                )
    except csv.Error:
        return [], ["CSV 형식을 읽을 수 없음: 따옴표나 줄바꿈이 올바른지 확인하세요."]

    if not students and not errors:
        errors.append("학생이 한 명도 없음: 열 이름 아래 줄에 학생 정보가 있어야 합니다.")

    if errors:
        return [], errors
    return students, []


def register_roster(conn, admin_student_no, students, team_count, password_hash):
    """
    명단으로 처음 상태를 만든다. (과제 공고 2.6절)

    run_db 안에서 실행되므로 이 함수 전체가 하나의 트랜잭션이다.
    중간에 오류가 나면 아래 작업이 모두 취소되어 이전 상태가 그대로 남는다.
    """
    with conn.cursor() as cur:
        # 1) 관리자인지 DB에서 다시 확인한다. (화면에서 숨기는 것만 믿지 않는다)
        cur.execute(
            "select is_admin from tf_students where student_no = %s",
            (admin_student_no,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            raise NotAdmin()

        # 2) 지원, 투표, 팀원, 마감 표시, 학생(관리자는 남김), 팀을 지운다.
        cur.execute("delete from tf_votes")
        cur.execute("delete from tf_applications")
        cur.execute("delete from tf_members")
        cur.execute("delete from tf_student_sub_roles")
        cur.execute("delete from tf_students where is_admin = false")
        cur.execute("delete from tf_teams")
        cur.execute("delete from tf_settings where key = %s", (SETTING_CLOSED_KEY,))

        # 3) 학생을 넣는다. (비밀번호는 해시만 저장한다)
        inserted = execute_values(
            cur,
            "insert into tf_students (student_no, name, main_role, password_hash, is_admin) "
            "values %s returning id, student_no",
            [
                (s["student_no"], s["name"], s["main_role"], password_hash, False)
                for s in students
            ],
            fetch=True,
        )
        id_of = {student_no: student_id for student_id, student_no in inserted}

        # 4) 보조 역할을 넣는다. (없는 학생은 한 줄도 넣지 않는다)
        sub_role_rows = [
            (id_of[s["student_no"]], role) for s in students for role in s["sub_roles"]
        ]
        if sub_role_rows:
            execute_values(
                cur,
                "insert into tf_student_sub_roles (student_id, role) values %s",
                sub_role_rows,
            )

        # 5) 빈 팀(팀1, 팀2, ...)을 만든다.
        execute_values(
            cur,
            "insert into tf_teams (name) values %s",
            [(f"팀{number}",) for number in range(1, team_count + 1)],
        )


def handle_roster_upload(admin_student_no, uploaded_file, team_count):
    """명단 올리기를 처리하고 (안내 문구, 자세한 내용 목록) 을 돌려준다."""
    if uploaded_file is None:
        return "막힘: 명단 CSV 파일을 먼저 선택하세요.", []

    # DB를 건드리기 전에 CSV 를 전부 검사한다.
    students, errors = parse_roster_csv(uploaded_file.getvalue())
    if errors:
        details = errors[:MAX_SHOWN_ERRORS]
        if len(errors) > MAX_SHOWN_ERRORS:
            details.append(f"... 그 밖에 {len(errors) - MAX_SHOWN_ERRORS}건")
        return f"막힘: CSV 파일에 문제가 있어 등록하지 않았음 (오류 {len(errors)}건)", details

    # 해시 계산은 느리므로 트랜잭션을 열기 전에 한 번만 한다. (모든 학생의 비밀번호가 같다)
    password_hash = hash_password(INITIAL_PASSWORD)

    try:
        run_db(
            lambda conn: register_roster(
                conn, admin_student_no, students, int(team_count), password_hash
            )
        )
    except NotAdmin:
        return "막힘: 관리자만 명단을 올릴 수 있음", []
    except psycopg2.Error as error:
        return (
            "막힘: 데이터베이스 문제로 등록하지 못했음. 이전 상태는 그대로 남아 있음",
            [f"오류 종류: {type(error).__name__}"],
        )

    return f"승인: 학생 {len(students)}명과 팀 {int(team_count)}개를 만들었음", []


# ---------------------------------------------------------------------
# 팀 목록 읽기
# ---------------------------------------------------------------------
def parse_team_number(team_name):
    """'팀3' 같은 이름 끝의 숫자 3 을 돌려준다. 숫자가 없으면 None."""
    found = re.search(r"(\d+)\s*$", team_name)
    return int(found.group(1)) if found else None


def build_teams(rows):
    """
    DB에서 읽은 줄들을 팀 목록으로 묶는다. (DB를 건드리지 않는 함수)

    rows 의 한 줄: (팀 id, 팀 이름, 자리 번호, 학생 id, 학번, 이름, 주 역할, 보조 역할 목록)
    팀원이 없는 팀은 자리 번호부터 뒤쪽이 모두 None 이다. 그 팀도 목록에 남긴다.
    """
    teams = {}
    for team_id, team_name, slot_no, student_id, student_no, name, main_role, sub_roles in rows:
        team = teams.setdefault(
            team_id,
            {
                "id": team_id,
                "name": team_name,
                "number": parse_team_number(team_name),
                "members": [],
            },
        )
        if student_id is not None:
            team["members"].append(
                {
                    "slot_no": slot_no,
                    "student_id": student_id,
                    "student_no": student_no,
                    "name": name,
                    "main_role": main_role,
                    "sub_roles": list(sub_roles or []),
                }
            )

    for team in teams.values():
        team["members"].sort(key=lambda member: member["slot_no"])

    # 팀 번호 순서(팀1, 팀2, ..., 팀10)로 줄 세운다. 번호가 없는 팀은 맨 뒤.
    return sorted(
        teams.values(),
        key=lambda team: (team["number"] is None, team["number"] or 0, team["id"]),
    )


def load_teams(conn):
    """모든 팀과 팀원(이름, 주 역할, 보조 역할)을 읽는다. 팀원이 없는 팀도 포함한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.name,
                   m.slot_no, s.id, s.student_no, s.name, s.main_role,
                   coalesce(
                       array_agg(r.role order by r.role) filter (where r.role is not null),
                       '{}'
                   )
            from tf_teams t
            left join tf_members m on m.team_id = t.id
            left join tf_students s on s.id = m.student_id
            left join tf_student_sub_roles r on r.student_id = s.id
            group by t.id, t.name, m.slot_no, s.id, s.student_no, s.name, s.main_role
            order by t.id, m.slot_no
            """
        )
        rows = cur.fetchall()

    # 비밀번호 해시는 읽지 않는다.
    return build_teams(rows)


def team_key_suffix(team):
    """key 이름 끝에 붙일 번호. 번호는 id 가 아니라 팀 이름 '팀N' 의 N 이다."""
    if team["number"] is not None:
        return str(team["number"])
    return f"id_{team['id']}"


def team_container_key(team):
    """채점용 key 이름: team_1, team_2, ..."""
    return f"team_{team_key_suffix(team)}"


# ---------------------------------------------------------------------
# 팀 지원과 투표 - 규칙 판단 (DB를 건드리지 않는 함수들)
# ---------------------------------------------------------------------
# 필수 포함 역할: 모든 팀에 서로 다른 사람으로 1명씩 있어야 한다. (과제 공고 2.3절)
ROLE_PLANNER = "기획자"
ROLE_PROGRAMMER = "웹 프로그래머"
REQUIRED_ROLE_COUNT = 2

# tf_settings 에서 모집이 마감되었음을 뜻하는 값
SETTING_CLOSED_VALUE = "true"

# 지원이 막히거나 거절되는 이유 (공고의 문구를 그대로 쓴다)
REASON_CLOSED = "모집이 마감됨"
REASON_HAS_TEAM = "이미 팀이 있음"
REASON_PENDING = "결과를 기다리는 지원이 있음"
REASON_FULL = "팀이 꽉 참"
REASON_SAME_ROLE = "같은 주 역할의 팀원이 있음"
REASON_REQUIRED_ROLE = "필수 포함 역할을 맡을 학생의 자리가 모자람"


def count_filled_required_roles(people):
    """
    사람들이 필수 포함 역할 2개(기획자, 웹 프로그래머) 중 몇 개를 채울 수 있는지 센다.

    기획자와 웹 프로그래머는 서로 다른 사람이 맡아야 하므로,
    한 사람이 둘 다 할 수 있어도 하나로만 센다. (과제 공고 3장)
    people 의 각 항목은 "roles"(주 역할과 보조 역할을 합친 집합)를 가진다.
    """
    planners = [i for i, person in enumerate(people) if ROLE_PLANNER in person["roles"]]
    programmers = [i for i, person in enumerate(people) if ROLE_PROGRAMMER in person["roles"]]

    if not planners and not programmers:
        return 0
    if not planners or not programmers:
        return 1

    # 둘 다 맡을 사람이 있을 때: 서로 다른 두 사람을 고를 수 있으면 2개, 아니면 1개
    for planner in planners:
        for programmer in programmers:
            if planner != programmer:
                return 2
    return 1


def check_team_rules(members, applicant):
    """
    applicant 가 members 의 팀에 들어가도 되는지 검사한다. 어기면 이유를, 괜찮으면 None 을 돌려준다.
    지원할 때와 승인 직전에 같은 검사를 쓴다.
    """
    # 1) 정원: 팀이 4명이면 더 들어갈 수 없다.
    if len(members) >= TEAM_MAX_SIZE:
        return REASON_FULL

    # 2) 주 역할이 같은 팀원이 있으면 안 된다. (주 역할만 따진다)
    if any(member["main_role"] == applicant["main_role"] for member in members):
        return REASON_SAME_ROLE

    # 3) 필수 포함 역할 자리: 지원자가 들어간 뒤 남는 자리 수가,
    #    아직 채우지 못한 필수 포함 역할 수보다 적으면 안 된다. (주 역할과 보조 역할을 모두 따진다)
    after = members + [applicant]
    remaining_slots = TEAM_MAX_SIZE - len(after)
    unfilled_roles = REQUIRED_ROLE_COUNT - count_filled_required_roles(after)
    if remaining_slots < unfilled_roles:
        return REASON_REQUIRED_ROLE

    return None


def decide_apply(closed, has_team, has_pending, members, applicant):
    """
    지원 단추를 눌렀을 때의 결과를 정한다. (결과 단어, 설명) 을 돌려준다.
    결과 단어: "막힘"(접수하지 않음), "승인"(빈 팀이라 바로 승인), "대기"(팀원의 투표를 기다림)
    """
    if closed:
        return "막힘", REASON_CLOSED
    if has_team:
        return "막힘", REASON_HAS_TEAM
    if has_pending:
        return "막힘", REASON_PENDING

    reason = check_team_rules(members, applicant)
    if reason:
        return "막힘", reason

    if not members:
        return "승인", "빈 팀이라 투표 없이 바로 팀원이 됨"
    return "대기", "팀원의 투표를 기다리는 중"


def evaluate_application(latest_vote, members, votes, applicant, applicant_has_team):
    """
    투표가 하나 들어온 뒤 지원의 상태를 정한다. (결과 단어, 설명) 을 돌려준다.

    members : 지금 이 팀의 팀원들 (투표할 사람은 "투표하는 때의 팀원"이다)
    votes   : {투표한 학생 id: "찬성" 또는 "거부"}  (방금 한 투표 포함)
    """
    # 한 명이라도 거부하면 다른 팀원을 기다리지 않고 바로 거절
    if latest_vote == "거부":
        return "거절", "팀원이 거부함"

    # 아직 찬성하지 않은 팀원이 있으면 대기
    if any(votes.get(member["student_id"]) != "찬성" for member in members):
        return "대기", "아직 투표하지 않은 팀원이 있음"

    # 모든 팀원이 찬성했다. 승인 직전에 규칙을 다시 검사한다. (같은 팀에 대기 중인 지원이 여럿일 때,
    # 앞의 지원이 먼저 승인되어 팀이 바뀌었을 수 있기 때문이다)
    if applicant_has_team:
        return "거절", "승인 직전 검사에서 이미 다른 팀에 속해 있음"

    reason = check_team_rules(members, applicant)
    if reason:
        return "거절", f"승인 직전 검사에서 규칙을 어김 ({reason})"

    return "승인", "모든 팀원이 찬성해 팀원이 됨"


# ---------------------------------------------------------------------
# 팀 지원과 투표 - DB 읽기와 쓰기 (한 문장씩 하는 작은 함수들)
#   아래 함수들은 run_db 안에서 부르므로, 한 번의 동작 전체가 하나의 트랜잭션이 된다.
# ---------------------------------------------------------------------
def make_person(row):
    """(학생 id, 학번, 이름, 주 역할, 보조 역할 목록) 한 줄을 규칙 검사용 dict 로 바꾼다."""
    student_id, student_no, name, main_role, sub_roles = row
    return {
        "student_id": student_id,
        "student_no": student_no,
        "name": name,
        "main_role": main_role,
        "roles": {main_role, *(sub_roles or [])},  # 주 역할 + 보조 역할
    }


def lock_team(cur, team_id):
    """팀 한 줄을 잠근다. 같은 팀에 대한 동작이 한 번에 하나씩만 처리되게 한다. 팀이 있으면 True."""
    cur.execute("select id from tf_teams where id = %s for update", (team_id,))
    return cur.fetchone() is not None


def lock_student(cur, student_id):
    """학생 한 줄을 잠그고 관리자 여부를 돌려준다. 학생이 없으면 None."""
    cur.execute("select is_admin from tf_students where id = %s for update", (student_id,))
    row = cur.fetchone()
    return None if row is None else row[0]


def load_person(cur, student_id):
    """학생 한 명의 이름과 역할(주 역할, 보조 역할)을 읽는다. 없으면 None."""
    cur.execute(
        """
        select s.id, s.student_no, s.name, s.main_role,
               coalesce(array_agg(r.role) filter (where r.role is not null), '{}')
        from tf_students s
        left join tf_student_sub_roles r on r.student_id = s.id
        where s.id = %s
        group by s.id
        """,
        (student_id,),
    )
    row = cur.fetchone()
    return make_person(row) if row else None


def load_members(cur, team_id):
    """팀의 지금 팀원들(역할 포함)을 자리 번호 순서로 읽는다."""
    cur.execute(
        """
        select s.id, s.student_no, s.name, s.main_role,
               coalesce(array_agg(r.role) filter (where r.role is not null), '{}')
        from tf_members m
        join tf_students s on s.id = m.student_id
        left join tf_student_sub_roles r on r.student_id = s.id
        where m.team_id = %s
        group by s.id, m.slot_no
        order by m.slot_no
        """,
        (team_id,),
    )
    return [make_person(row) for row in cur.fetchall()]


def is_recruitment_closed(cur):
    """모집이 마감되었으면 True."""
    cur.execute("select value from tf_settings where key = %s", (SETTING_CLOSED_KEY,))
    row = cur.fetchone()
    return bool(row) and row[0] == SETTING_CLOSED_VALUE


def student_has_team(cur, student_id):
    cur.execute("select 1 from tf_members where student_id = %s", (student_id,))
    return cur.fetchone() is not None


def student_has_pending(cur, student_id):
    """결과를 기다리는(대기 중인) 지원이 있으면 True."""
    cur.execute(
        "select 1 from tf_applications where student_id = %s and status = '대기'",
        (student_id,),
    )
    return cur.fetchone() is not None


def insert_application(cur, team_id, student_id, status, reason):
    cur.execute(
        "insert into tf_applications (team_id, student_id, status, reason) "
        "values (%s, %s, %s, %s) returning id",
        (team_id, student_id, status, reason),
    )
    return cur.fetchone()[0]


def add_member(cur, team_id, student_id):
    """팀의 가장 작은 빈 자리(1~4)에 학생을 넣는다."""
    cur.execute("select slot_no from tf_members where team_id = %s", (team_id,))
    used = {row[0] for row in cur.fetchall()}
    free = [number for number in range(1, TEAM_MAX_SIZE + 1) if number not in used]
    if not free:
        raise NoFreeSlot()
    cur.execute(
        "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
        (team_id, free[0], student_id),
    )


def find_application_team(cur, application_id):
    """지원이 들어간 팀의 id. 지원이 없으면 None."""
    cur.execute("select team_id from tf_applications where id = %s", (application_id,))
    row = cur.fetchone()
    return None if row is None else row[0]


def lock_application(cur, application_id):
    """지원 한 줄을 잠그고 (지원자 id, 상태) 를 돌려준다. 없으면 None."""
    cur.execute(
        "select student_id, status from tf_applications where id = %s for update",
        (application_id,),
    )
    row = cur.fetchone()
    return None if row is None else (row[0], row[1])


def get_vote(cur, application_id, voter_id):
    """이 학생이 이 지원에 이미 한 투표("찬성"/"거부"). 없으면 None."""
    cur.execute(
        "select vote from tf_votes where application_id = %s and voter_id = %s",
        (application_id, voter_id),
    )
    row = cur.fetchone()
    return None if row is None else row[0]


def insert_vote(cur, application_id, voter_id, vote):
    cur.execute(
        "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)",
        (application_id, voter_id, vote),
    )


def load_votes(cur, application_id):
    """이 지원에 들어온 투표 전부: {투표한 학생 id: 투표}"""
    cur.execute(
        "select voter_id, vote from tf_votes where application_id = %s",
        (application_id,),
    )
    return {voter_id: vote for voter_id, vote in cur.fetchall()}


def set_application_status(cur, application_id, status, reason):
    cur.execute(
        "update tf_applications set status = %s, reason = %s where id = %s",
        (status, reason, application_id),
    )


def apply_to_team(conn, student_id, team_id):
    """
    학생이 팀에 지원한다. (결과 단어, 설명) 을 돌려준다.
    막힘은 DB에 기록하지 않는다. 승인과 대기는 지원으로 기록한다.
    """
    with conn.cursor() as cur:
        if not lock_team(cur, team_id):
            return "막힘", "팀을 찾을 수 없음"

        is_admin = lock_student(cur, student_id)
        if is_admin is None:
            return "막힘", "계정을 찾을 수 없음"
        if is_admin:
            return "막힘", "관리자는 팀에 지원할 수 없음"

        word, text = decide_apply(
            closed=is_recruitment_closed(cur),
            has_team=student_has_team(cur, student_id),
            has_pending=student_has_pending(cur, student_id),
            members=load_members(cur, team_id),
            applicant=load_person(cur, student_id),
        )

        if word == "승인":  # 빈 팀: 투표할 팀원이 없으므로 바로 팀원이 된다.
            insert_application(cur, team_id, student_id, "승인", None)
            add_member(cur, team_id, student_id)
        elif word == "대기":
            insert_application(cur, team_id, student_id, "대기", None)

        return word, text


def cast_vote(conn, voter_id, application_id, vote):
    """
    팀원이 지원에 투표한다. (결과 단어, 설명) 을 돌려준다. 결과 단어는 그 지원의 지금 상태다.
    투표 기록과 지원 상태 변경, 팀원 추가는 한 번의 트랜잭션으로 처리한다.
    """
    with conn.cursor() as cur:
        team_id = find_application_team(cur, application_id)
        if team_id is None:
            return "막힘", "지원을 찾을 수 없음"

        # 같은 팀에 대한 동작이 겹치지 않도록 팀을 잠근 뒤, 지원의 최신 상태를 읽는다.
        lock_team(cur, team_id)
        locked = lock_application(cur, application_id)
        if locked is None:
            return "막힘", "지원을 찾을 수 없음"
        applicant_id, status = locked

        if status != "대기":
            return status, "이미 결과가 나온 지원임"
        if is_recruitment_closed(cur):
            return "막힘", REASON_CLOSED

        # 투표할 사람은 "투표하는 때의 팀원"이다.
        members = load_members(cur, team_id)
        if voter_id not in {member["student_id"] for member in members}:
            return "막힘", "이 팀의 팀원만 투표할 수 있음"

        previous = get_vote(cur, application_id, voter_id)
        if previous is not None:  # 한 번 투표하면 바꿀 수 없다.
            return "대기", f"이미 투표했음 (내 투표: {previous})"

        insert_vote(cur, application_id, voter_id, vote)

        word, text = evaluate_application(
            latest_vote=vote,
            members=members,
            votes=load_votes(cur, application_id),
            applicant=load_person(cur, applicant_id),
            applicant_has_team=student_has_team(cur, applicant_id),
        )

        if word == "승인":
            add_member(cur, team_id, applicant_id)
            set_application_status(cur, application_id, "승인", None)
        elif word == "거절":
            set_application_status(cur, application_id, "거절", text)

        return word, text


def load_student_screen(conn, student_id):
    """
    학생 화면에 필요한 것을 한 번에 읽는다. (팀 목록, 화면 정보) 를 돌려준다.
      화면 정보: closed(마감 여부), pending(내 대기 중인 지원), incoming(내 팀에 들어온 지원들)
    """
    teams = load_teams(conn)

    with conn.cursor() as cur:
        closed = is_recruitment_closed(cur)

        # 내가 낸 지원 중 결과를 기다리는 것
        cur.execute(
            "select id, team_id from tf_applications where student_id = %s and status = '대기'",
            (student_id,),
        )
        row = cur.fetchone()
        pending = {"application_id": row[0], "team_id": row[1]} if row else None

        # 내 팀에 들어온, 결과를 기다리는 지원들
        my_team = next(
            (
                team
                for team in teams
                if any(member["student_id"] == student_id for member in team["members"])
            ),
            None,
        )
        incoming = []
        if my_team is not None:
            cur.execute(
                """
                select a.id, s.student_no, s.name, s.main_role,
                       coalesce(array_agg(r.role order by r.role) filter (where r.role is not null), '{}')
                from tf_applications a
                join tf_students s on s.id = a.student_id
                left join tf_student_sub_roles r on r.student_id = s.id
                where a.team_id = %s and a.status = '대기'
                group by a.id, s.id
                order by a.created_at, a.id
                """,
                (my_team["id"],),
            )
            applications = cur.fetchall()

            votes = {}  # {지원 id: {투표한 학생 id: 투표}}
            if applications:
                cur.execute(
                    "select application_id, voter_id, vote from tf_votes "
                    "where application_id = any(%s)",
                    ([application[0] for application in applications],),
                )
                for application_id, voter_id, vote in cur.fetchall():
                    votes.setdefault(application_id, {})[voter_id] = vote

            for application_id, student_no, name, main_role, sub_roles in applications:
                application_votes = votes.get(application_id, {})
                incoming.append(
                    {
                        "application_id": application_id,
                        "student_no": student_no,
                        "name": name,
                        "main_role": main_role,
                        "sub_roles": list(sub_roles),
                        "my_vote": application_votes.get(student_id),
                        "yes_count": sum(1 for vote in application_votes.values() if vote == "찬성"),
                        "member_count": len(my_team["members"]),
                    }
                )

    return teams, {"closed": closed, "pending": pending, "incoming": incoming}


# ---------------------------------------------------------------------
# 모집 마감, 배정 검사, 자체 배정, AI 배정, 배정 확정 (과제 공고 2.5절)
#   - 규칙 판단과 계산은 DB를 건드리지 않는 함수로 따로 만들어 두었다. (테스트하기 쉽다)
#   - DB를 건드리는 함수는 run_db 안에서 부르므로, 한 번의 동작이 하나의 트랜잭션이 된다.
# ---------------------------------------------------------------------

# 확정한 팀의 최소 인원 (과제 공고 2.3절: 모든 팀이 2~4명)
MIN_TEAM_SIZE = 2

# 모집 마감 때 대기 중이던 지원을 거절하는 이유
REASON_CLOSE_REJECT = "모집이 마감되어 거절됨"

# OpenRouter 호출 설정
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_TIMEOUT_SECONDS = 120  # 모델 하나를 부른 때부터 응답을 받을 때까지의 전체 제한 (공고 2.5절 5항)
AI_MAX_TOKENS = 6000
AI_MODEL_COUNT = 3

# 1차, 2차, 3차 모델 이름.
#   * 무료 여부와 실제 호출 가능 여부를 직접 확인한 모델 이름만 넣는다.
#   * 비워 두면(빈 문자열) 그 차례는 건너뛰고, 3개 모두 비어 있으면 앱이 스스로 배정한다.
#   * 코드를 고치지 않고 바꾸려면 .env 또는 Streamlit Secrets 에
#       OPENROUTER_MODELS = "모델1,모델2,모델3"
#     처럼 쉼표로 구분해 넣는다. (이 값이 있으면 아래 목록보다 우선한다)
AI_MODELS = ["", "", ""]

# 공고 6.3절 14번: 무료 모델로 자동 연결하는 라우터는 쓰면 감점이다.
FORBIDDEN_MODEL_NAMES = {"openrouter/free"}

# 자체 배정(완전탐색)이 살펴볼 최대 횟수. 이 횟수를 넘으면 탐색을 멈춘다.
SEARCH_NODE_LIMIT = 500000


class AiCallError(Exception):
    """AI 호출이 실패했을 때 쓰는 오류. 안내 문구만 담는다. (키 같은 비밀 값은 담지 않는다)"""


class AiTimeout(AiCallError):
    """AI 응답이 제한 시간 안에 오지 않았을 때 쓰는 오류"""


# ---------------------------------------------------------------------
# 모집 마감 - DB
# ---------------------------------------------------------------------
def require_admin(cur, admin_student_no):
    """DB에서 관리자인지 다시 확인한다. 관리자가 아니면 NotAdmin 을 일으킨다."""
    cur.execute("select is_admin from tf_students where student_no = %s", (admin_student_no,))
    row = cur.fetchone()
    if not row or not row[0]:
        raise NotAdmin()


def lock_all_teams(cur):
    """모든 팀을 id 순서로 잠근다. (지원과 투표는 팀 한 줄을 잠그므로, 마감과 겹치지 않는다)"""
    cur.execute("select id from tf_teams order by id for update")
    return [row[0] for row in cur.fetchall()]


def close_recruitment(conn, admin_student_no):
    """
    모집을 마감한다. (결과 단어, 설명) 을 돌려준다. (과제 공고 2.5절 1~2항)
      1) 마감 표시를 저장한다. 이 뒤로는 지원과 투표를 할 수 없다.
      2) 대기 중인 지원을 모두 거절한다.
      3) 1명뿐인 팀의 학생은 팀에서 빠져 "팀이 없는 학생"이 된다.
    한 번의 트랜잭션이므로 중간에 실패하면 모두 취소된다.
    """
    with conn.cursor() as cur:
        require_admin(cur, admin_student_no)

        if not lock_all_teams(cur):
            return "막힘", "팀이 없음. 먼저 명단을 올려 처음 상태를 만드세요"

        if is_recruitment_closed(cur):
            return "막힘", "이미 모집이 마감되어 있음"

        cur.execute(
            "insert into tf_settings (key, value) values (%s, %s) "
            "on conflict (key) do update set value = excluded.value",
            (SETTING_CLOSED_KEY, SETTING_CLOSED_VALUE),
        )

        cur.execute(
            "update tf_applications set status = '거절', reason = %s where status = '대기'",
            (REASON_CLOSE_REJECT,),
        )
        rejected = cur.rowcount

        cur.execute(
            "select student_id from tf_members where team_id in "
            "(select team_id from tf_members group by team_id having count(*) = 1)"
        )
        lone_ids = [row[0] for row in cur.fetchall()]
        if lone_ids:
            cur.execute("delete from tf_members where student_id = any(%s)", (lone_ids,))

    return (
        "승인",
        f"모집을 마감함 (대기 중이던 지원 {rejected}건 거절, "
        f"1명뿐인 팀의 학생 {len(lone_ids)}명이 팀에서 빠져 팀이 없는 학생이 됨)",
    )


# ---------------------------------------------------------------------
# 배정에 필요한 정보 읽기 - DB
# ---------------------------------------------------------------------
def load_team_state(cur):
    """팀 목록과 팀원(역할 포함)을 읽는다. 팀원이 없는 팀도 포함한다."""
    cur.execute("select id, name from tf_teams order by id")
    teams = [
        {
            "id": team_id,
            "name": name,
            "number": parse_team_number(name),
            "members": load_members(cur, team_id),
        }
        for team_id, name in cur.fetchall()
    ]
    teams.sort(key=lambda team: (team["number"] is None, team["number"] or 0, team["id"]))
    return teams


def load_unassigned(cur):
    """
    팀이 없는 학생들을 학번 순서로 읽는다. (관리자는 제외)
    prev_team_id 는 그 학생이 승인되어 들어갔던 팀이다. 마감 때 해산된 학생이 원래 팀으로
    돌아갈 수 있는지 따져 볼 때만 쓴다. 승인된 적이 없으면 None 이다.
    """
    cur.execute(
        """
        select s.id, s.student_no, s.name, s.main_role,
               coalesce(array_agg(r.role order by r.role) filter (where r.role is not null), '{}'),
               (select a.team_id from tf_applications a
                 where a.student_id = s.id and a.status = '승인'
                 order by a.id desc limit 1)
        from tf_students s
        left join tf_student_sub_roles r on r.student_id = s.id
        where s.is_admin = false
          and not exists (select 1 from tf_members m where m.student_id = s.id)
        group by s.id
        order by s.student_no
        """
    )
    people = []
    for student_id, student_no, name, main_role, sub_roles, prev_team_id in cur.fetchall():
        person = make_person((student_id, student_no, name, main_role, sub_roles))
        person["sub_roles"] = list(sub_roles or [])
        person["prev_team_id"] = prev_team_id
        people.append(person)
    return people


def load_unassigned_students(conn):
    """화면용: 팀이 없는 학생 목록."""
    with conn.cursor() as cur:
        return load_unassigned(cur)


def load_assignment_inputs(conn, admin_student_no):
    """AI 배정에 필요한 정보(마감 여부, 팀, 팀이 없는 학생)를 읽는다. 관리자만 쓸 수 있다."""
    with conn.cursor() as cur:
        require_admin(cur, admin_student_no)
        return {
            "closed": is_recruitment_closed(cur),
            "teams": load_team_state(cur),
            "unassigned": load_unassigned(cur),
        }


# ---------------------------------------------------------------------
# 배정안 검사 - DB를 건드리지 않는 함수들 (과제 공고 2.5절 4항의 다섯 가지)
# ---------------------------------------------------------------------
def validate_final_team(members):
    """
    확정한 팀 하나가 규칙을 지키는지 검사한다. 어긴 내용의 목록을 돌려준다. (비어 있으면 통과)
    지원할 때 쓰는 check_team_rules 와 달리, 필수 포함 역할이 "실제로" 채워져 있어야 한다.
    """
    problems = []
    size = len(members)
    if size < MIN_TEAM_SIZE or size > TEAM_MAX_SIZE:
        problems.append(f"인원이 {size}명임 ({MIN_TEAM_SIZE}~{TEAM_MAX_SIZE}명이어야 함)")

    main_roles = [member["main_role"] for member in members]
    repeated = sorted({role for role in main_roles if main_roles.count(role) > 1})
    if repeated:
        problems.append("주 역할이 겹침: " + ", ".join(repeated))

    if count_filled_required_roles(members) < REQUIRED_ROLE_COUNT:
        has_planner = any(ROLE_PLANNER in member["roles"] for member in members)
        has_programmer = any(ROLE_PROGRAMMER in member["roles"] for member in members)
        if not has_planner:
            problems.append(f"{ROLE_PLANNER}를 맡을 학생이 없음")
        if not has_programmer:
            problems.append(f"{ROLE_PROGRAMMER}를 맡을 학생이 없음")
        if has_planner and has_programmer:
            problems.append(f"{ROLE_PLANNER}와 {ROLE_PROGRAMMER}를 서로 다른 학생이 맡을 수 없음")

    return problems


def validate_assignment(teams, unassigned, assignment):
    """
    배정안 {학생 id: 팀 id} 을 다섯 가지로 검사한다. 어긴 내용의 목록을 돌려준다. (비어 있으면 통과)
      1) 팀이 없는 학생이 빠짐없이 배정됨   2) 한 학생은 한 팀에만 배정됨(딕셔너리라서 저절로 지켜짐)
      3) 모든 팀이 2~4명   4) 팀 안에서 주 역할 중복 없음   5) 필수 포함 역할 충족
    이미 팀이 있는 학생이 배정안에 들어 있으면(옮기려 하면) 그것도 어긴 것으로 본다.
    """
    problems = []
    unassigned_by_id = {person["student_id"]: person for person in unassigned}
    team_ids = {team["id"] for team in teams}

    for student_id, team_id in assignment.items():
        if student_id not in unassigned_by_id:
            problems.append("팀이 없는 학생이 아닌 학생이 배정안에 있음 (이미 팀이 있는 학생은 옮길 수 없음)")
            break
    for team_id in set(assignment.values()):
        if team_id not in team_ids:
            problems.append("없는 팀에 배정함")
            break

    left_out = [
        person["name"] for person in unassigned if person["student_id"] not in assignment
    ]
    if left_out:
        problems.append("배정되지 않은 학생이 있음: " + ", ".join(left_out))

    members_of = {team["id"]: list(team["members"]) for team in teams}
    for student_id, team_id in assignment.items():
        if student_id in unassigned_by_id and team_id in members_of:
            members_of[team_id].append(unassigned_by_id[student_id])

    for team in teams:
        team_problems = validate_final_team(members_of[team["id"]])
        if team_problems:
            problems.append(f"{team['name']}: " + " / ".join(team_problems))

    return problems


def explain_no_assignment(teams, unassigned):
    """규칙을 지키는 배정이 없을 때, 사람이 읽을 이유 목록을 만든다. (공고 2.5절 8항)"""
    reasons = []

    free_slots = sum(TEAM_MAX_SIZE - len(team["members"]) for team in teams)
    if len(unassigned) > free_slots:
        reasons.append(
            f"빈 자리가 모자람: 팀이 없는 학생은 {len(unassigned)}명인데 빈 자리는 {free_slots}개임"
        )

    needed = sum(max(0, MIN_TEAM_SIZE - len(team["members"])) for team in teams)
    if needed > len(unassigned):
        reasons.append(
            f"인원이 모자람: 모든 팀을 {MIN_TEAM_SIZE}명 이상으로 채우려면 학생 {needed}명이 더 필요한데 "
            f"팀이 없는 학생은 {len(unassigned)}명임"
        )

    for team in teams:
        members = team["members"]
        unfilled = REQUIRED_ROLE_COUNT - count_filled_required_roles(members)
        if unfilled <= 0:
            continue

        # 이 팀에 들어갈 수 있는 학생: 주 역할이 팀원과 겹치지 않는 학생
        usable = [
            person
            for person in unassigned
            if all(person["main_role"] != member["main_role"] for member in members)
        ]
        pool = members + usable
        has_planner = any(ROLE_PLANNER in person["roles"] for person in pool)
        has_programmer = any(ROLE_PROGRAMMER in person["roles"] for person in pool)
        team_free = TEAM_MAX_SIZE - len(members)

        if not has_planner:
            reasons.append(f"{team['name']}에 {ROLE_PLANNER}를 맡을 학생이 없음")
        if not has_programmer:
            reasons.append(f"{team['name']}에 {ROLE_PROGRAMMER}를 맡을 학생이 없음")
        if has_planner and has_programmer:
            if count_filled_required_roles(pool) < REQUIRED_ROLE_COUNT:
                reasons.append(
                    f"{team['name']}에 {ROLE_PLANNER}와 {ROLE_PROGRAMMER}를 서로 다른 학생이 맡을 수 없음"
                )
            elif unfilled > team_free:
                reasons.append(
                    f"{team['name']}은 빈 자리가 {team_free}개라 필수 포함 역할 {unfilled}개를 채울 수 없음"
                )

    if not reasons:
        reasons.append("모든 경우를 따져 봤지만 여러 팀의 조건이 서로 부딪혀 규칙을 지키는 배정이 없음")
    return reasons


# ---------------------------------------------------------------------
# 앱의 자체 배정 - 모든 경우를 따져 끝까지 찾는다 (공고 3장 "3차 모델까지 실패"의 어려운 해결)
# ---------------------------------------------------------------------
def find_assignment(teams, unassigned, node_limit=SEARCH_NODE_LIMIT):
    """
    팀이 없는 학생을 팀에 넣는 방법을 완전탐색(백트래킹)으로 찾는다.
    (배정안 {학생 id: 팀 id} 또는 None, 끝까지 따져 봤는지 True/False) 를 돌려준다.

    * 이미 팀에 있는 학생은 옮기지 않는다. (팀이 없는 학생만 넣는다)
    * 5가지 검사를 모두 통과하는 배정만 후보가 된다.
    * 후보가 여럿이면, 마감 때 해산된 학생이 원래 팀으로 돌아가는 수가 가장 많은 배정을 고른다.
      (원래 팀 복귀는 규칙을 모두 지키는 후보들 사이에서만 따진다. 복귀 때문에 규칙을 어기지 않는다.)
    """
    team_ids = [team["id"] for team in teams]
    lists = {team["id"]: list(team["members"]) for team in teams}

    if not unassigned:
        ok = all(not validate_final_team(members) for members in lists.values())
        return ({} if ok else None), True

    def eligible_count(student):
        return sum(
            1
            for members in lists.values()
            if len(members) < TEAM_MAX_SIZE
            and all(member["main_role"] != student["main_role"] for member in members)
        )

    # 들어갈 수 있는 팀이 적은 학생부터 놓으면 막다른 길을 빨리 알아챈다.
    order = sorted(unassigned, key=lambda student: (eligible_count(student), student["student_no"]))
    max_score = sum(1 for student in unassigned if student.get("prev_team_id") in lists)

    best = {"score": -1, "assignment": None}
    state = {"nodes": 0, "limited": False}
    chosen = {}

    def still_possible(remaining):
        """남은 학생 수로 최소 인원과 필수 포함 역할을 채울 수 있는지 대강 따진다. (불가능하면 가지를 친다)"""
        free = 0
        needed = 0
        for members in lists.values():
            size = len(members)
            free += TEAM_MAX_SIZE - size
            needed += max(0, MIN_TEAM_SIZE - size)
            if REQUIRED_ROLE_COUNT - count_filled_required_roles(members) > TEAM_MAX_SIZE - size:
                return False
        return needed <= remaining <= free

    def search(index):
        if state["limited"] or best["score"] == max_score:
            return  # 이미 더 나아질 수 없는 배정을 찾았거나, 탐색 횟수 제한에 걸림
        state["nodes"] += 1
        if state["nodes"] > node_limit:
            state["limited"] = True
            return

        if index == len(order):
            if all(not validate_final_team(members) for members in lists.values()):
                score = sum(
                    1 for student in order if chosen[student["student_id"]] == student.get("prev_team_id")
                )
                if score > best["score"]:
                    best["score"] = score
                    best["assignment"] = dict(chosen)
            return

        student = order[index]
        previous = student.get("prev_team_id")
        # 원래 팀을 가장 먼저 시도한다. (규칙을 지키는 경우에만 끝까지 가므로 규칙이 우선이다)
        for team_id in sorted(team_ids, key=lambda tid: (tid != previous, tid)):
            members = lists[team_id]
            if len(members) >= TEAM_MAX_SIZE:
                continue
            if any(member["main_role"] == student["main_role"] for member in members):
                continue
            members.append(student)
            chosen[student["student_id"]] = team_id
            if still_possible(len(order) - index - 1):
                search(index + 1)
            members.pop()
            del chosen[student["student_id"]]

    if not still_possible(len(order)):
        return None, True

    search(0)
    return best["assignment"], not state["limited"]


# ---------------------------------------------------------------------
# AI 배정 - 요청 만들기, 호출하기, 응답 읽기
# ---------------------------------------------------------------------
def describe_person(person):
    sub_roles = ", ".join(person.get("sub_roles") or []) or "없음"
    return f"{person['name']} (주 역할: {person['main_role']}, 보조 역할: {sub_roles})"


def build_ai_messages(teams, unassigned):
    """AI 에게 보낼 메시지를 만든다. (지금의 팀 구성, 팀이 없는 학생과 역할, 규칙)"""
    team_name_of = {team["id"]: team["name"] for team in teams}

    team_info = [
        {
            "team": team["name"],
            "members": [
                {
                    "name": member["name"],
                    "main_role": member["main_role"],
                    "sub_roles": sorted(role for role in member["roles"] if role != member["main_role"]),
                }
                for member in team["members"]
            ],
        }
        for team in teams
    ]

    student_info = []
    for person in unassigned:
        info = {
            "student_no": person["student_no"],
            "name": person["name"],
            "main_role": person["main_role"],
            "sub_roles": person.get("sub_roles") or [],
        }
        if person.get("prev_team_id") in team_name_of:
            info["previous_team"] = team_name_of[person["prev_team_id"]]
        student_info.append(info)

    rules = (
        "규칙:\n"
        "1. 팀이 없는 학생만 팀에 넣는다. 이미 팀에 있는 학생은 옮기지 않는다.\n"
        "2. 팀이 없는 학생 전원을 빠짐없이 배정하고, 한 학생은 한 팀에만 배정한다.\n"
        "3. 배정이 끝난 뒤 모든 팀은 2명 이상 4명 이하여야 한다. (빈 팀 없음)\n"
        "4. 한 팀 안에 주 역할(main_role)이 같은 학생이 2명 이상 있으면 안 된다.\n"
        "5. 모든 팀에는 기획자 역할을 맡을 학생과 웹 프로그래머 역할을 맡을 학생이 서로 다른 사람으로 "
        "1명씩 있어야 한다. 주 역할이나 보조 역할(sub_roles)로 맡을 수 있다.\n"
        "6. previous_team 이 있는 학생은 규칙을 모두 지킬 수 있을 때에 한해 그 팀으로 돌려보내는 것을 "
        "우선한다. 규칙이 항상 우선이다.\n"
    )
    answer_format = (
        '답은 JSON 만 출력한다. 설명, 마크다운, 코드 블록은 쓰지 않는다. 형식:\n'
        '{"assignments": [{"student_no": "학번", "team": "팀 이름"}]}'
    )
    user_text = (
        "팀 프로젝트의 팀이 없는 학생을 팀에 배정해 줘.\n\n"
        + rules
        + "\n현재 팀 구성:\n"
        + json.dumps(team_info, ensure_ascii=False)
        + "\n\n팀이 없는 학생:\n"
        + json.dumps(student_info, ensure_ascii=False)
        + "\n\n"
        + answer_format
    )
    return [
        {"role": "system", "content": "너는 팀 편성을 돕는 도우미다. 규칙을 정확히 지켜 JSON 으로만 답한다."},
        {"role": "user", "content": user_text},
    ]


def parse_ai_assignment(text, teams, unassigned):
    """
    AI 의 답(글자)을 읽어 배정안 {학생 id: 팀 id} 로 바꾼다. (배정안 또는 None, 실패 이유 또는 None)
    이 함수는 형식만 읽는다. 규칙을 지키는지는 validate_assignment 가 검사한다.
    """
    if not text or not str(text).strip():
        return None, "빈 응답"

    cleaned = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None, "JSON 을 찾을 수 없음"
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None, "JSON 을 읽을 수 없음"

    items = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None, "assignments 목록이 없음"

    team_id_of = {}
    for team in teams:
        team_id_of[team["name"]] = team["id"]
        if team["number"] is not None:
            team_id_of[str(team["number"])] = team["id"]
    person_of = {person["student_no"]: person for person in unassigned}
    already_in_team = {
        member["student_no"] for team in teams for member in team["members"]
    }

    assignment = {}
    for item in items:
        if not isinstance(item, dict):
            return None, "assignments 항목의 모양이 이상함"
        student_no = str(item.get("student_no", "")).strip()
        team_value = str(item.get("team", "")).strip()

        if student_no in already_in_team:
            return None, f"이미 팀이 있는 학생({student_no})을 옮기려 함"
        if student_no not in person_of:
            return None, f"팀이 없는 학생 목록에 없는 학번({student_no})"
        if team_value not in team_id_of:
            return None, f"없는 팀 이름({team_value})"

        student_id = person_of[student_no]["student_id"]
        if student_id in assignment:
            return None, f"한 학생({student_no})이 두 번 배정됨"
        assignment[student_id] = team_id_of[team_value]

    return assignment, None


def get_ai_models():
    """사용할 모델 이름 3개를 돌려준다. OPENROUTER_MODELS 값이 있으면 그것을, 없으면 AI_MODELS 를 쓴다."""
    raw = get_secret("OPENROUTER_MODELS")
    names = [name.strip() for name in raw.split(",")] if raw else list(AI_MODELS)
    names = (names + [""] * AI_MODEL_COUNT)[:AI_MODEL_COUNT]
    return names


def call_openrouter(api_key, model, messages, timeout_seconds):
    """
    OpenRouter 에 요청을 한 번 보내고 답 글자를 돌려준다. 실패하면 AiCallError.
    * requests 의 timeout 은 "응답이 시작될 때까지"만 재므로, 전체 대기 시간은 wait_with_deadline 이 잰다.
    * 오류 문구에는 키가 들어갈 수 없도록 상태 번호나 오류 종류만 담는다.
    """
    if requests is None:
        raise AiCallError("requests 패키지가 설치되어 있지 않음")

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": AI_MAX_TOKENS,
        "reasoning": {"effort": "low"},  # 생각하는 데 글자 수를 다 써서 빈 응답이 나오는 것을 줄인다.
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = requests.post(
            OPENROUTER_URL, headers=headers, json=body, timeout=(10, timeout_seconds + 10)
        )
    except requests.exceptions.RequestException as error:
        raise AiCallError(f"연결 오류 ({type(error).__name__})")

    if response.status_code != 200:
        raise AiCallError(f"HTTP {response.status_code}")

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AiCallError("응답 형식이 이상함")

    if not content or not str(content).strip():
        raise AiCallError("빈 응답")
    return str(content)


def wait_with_deadline(function, deadline_seconds, on_wait=None):
    """
    function() 을 다른 스레드에서 실행하고, 시작한 때부터 deadline_seconds 초 안에 끝나지 않으면
    AiTimeout 으로 끊는다. (전체 대기 시간 제한 - 공고 3장 "AI 응답이 늦을 때"의 어려운 해결)
    기다리는 동안 1초마다 on_wait(지난 초) 를 부른다.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(function)
    started = time.monotonic()
    try:
        while True:
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise AiTimeout(f"{deadline_seconds}초 안에 응답하지 않아 끊음")
            try:
                return future.result(timeout=min(1.0, remaining))
            except concurrent.futures.TimeoutError:
                if future.done():
                    raise  # function 안에서 난 오류이므로 그대로 올린다.
                if on_wait:
                    on_wait(int(time.monotonic() - started))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def run_ai_assignment(
    teams, unassigned, models, api_key, progress, caller=call_openrouter, deadline=AI_TIMEOUT_SECONDS
):
    """
    모델을 1차, 2차, 3차 순서로 불러 배정안을 받는다.
    (배정안 또는 None, 안내 줄 목록, 성공한 모델의 차례 또는 None) 을 돌려준다.
    응답이 없거나, 빈 응답이나 오류가 나거나, 배정안이 5가지 검사를 통과하지 못하면 다음 모델로 넘어간다.
    progress(줄 목록) 는 화면에 진행 안내를 보여 주는 함수다.
    """
    log = []

    if not api_key:
        log.append("OPENROUTER_API_KEY 값이 없어 AI 를 부르지 않음")
        progress(log)
        return None, log, None

    messages = build_ai_messages(teams, unassigned)

    for number, model in enumerate(models, start=1):
        label = f"{number}차 모델"
        if not model:
            log.append(f"{label}: 모델 이름이 비어 있어 건너뜀")
            progress(log)
            continue
        if model in FORBIDDEN_MODEL_NAMES:
            log.append(f"{label}: {model} 는 쓸 수 없는 이름이라 건너뜀")
            progress(log)
            continue

        def show_waiting(seconds, label=label, model=model):
            progress(log + [f"AI 가 생각하는 중: {label}({model})의 응답을 기다리는 중... {seconds}초 / {deadline}초"])

        show_waiting(0)
        try:
            text = wait_with_deadline(
                lambda model=model: caller(api_key, model, messages, deadline), deadline, show_waiting
            )
        except AiCallError as error:
            log.append(f"{label}({model}) 실패: {error}")
            progress(log)
            continue
        except Exception as error:  # 예상하지 못한 오류도 비밀 값 없이 종류만 알린다.
            log.append(f"{label}({model}) 실패: 알 수 없는 오류 ({type(error).__name__})")
            progress(log)
            continue

        assignment, problem = parse_ai_assignment(text, teams, unassigned)
        if problem:
            log.append(f"{label}({model}) 실패: 응답을 읽을 수 없음 - {problem}")
            progress(log)
            continue

        problems = validate_assignment(teams, unassigned, assignment)
        if problems:
            log.append(f"{label}({model}) 실패: 배정안이 검사를 통과하지 못함 - " + " / ".join(problems[:3]))
            progress(log)
            continue

        log.append(f"{label}({model}) 성공: 배정안이 5가지 검사를 모두 통과함")
        progress(log)
        return assignment, log, number

    return None, log, None


def format_plan(teams, unassigned, assignment):
    """관리자에게 보여 줄 배정안 줄 목록 (학생의 이름과 역할, 배정된 팀)."""
    team_name_of = {team["id"]: team["name"] for team in teams}
    lines = []
    for person in unassigned:
        team_id = assignment.get(person["student_id"])
        lines.append(f"{describe_person(person)} -> {team_name_of.get(team_id, '(없음)')}")
    return lines


def prepare_assignment(admin_student_no, progress):
    """
    AI 배정 단추의 동작. (배정안 또는 None, 안내 문구, 자세한 줄 목록) 을 돌려준다.
    순서: 마감 확인 -> 규칙을 지키는 배정이 있는지 앱이 먼저 확인 -> AI 1~3차 -> 모두 실패하면 앱이 스스로 배정
    """
    try:
        data = run_db(lambda conn: load_assignment_inputs(conn, admin_student_no))
    except NotAdmin:
        return None, "막힘: 관리자만 AI 배정을 할 수 있음", []
    except psycopg2.Error:
        return None, "막힘: 데이터베이스 문제로 배정하지 못했음. 잠시 뒤 다시 시도하세요", []

    teams = data["teams"]
    unassigned = data["unassigned"]

    if not teams:
        return None, "막힘: 팀이 없음. 먼저 명단을 올려 처음 상태를 만드세요", []
    if not data["closed"]:
        return None, "막힘: 모집을 먼저 마감하세요", []
    if not unassigned:
        return None, "막힘: 팀이 없는 학생이 없음", []

    # 규칙을 지키는 배정이 아예 없으면 AI 를 부르지 않는다. (공고 2.5절 8항)
    own_assignment, searched_all = find_assignment(teams, unassigned)
    if own_assignment is None:
        if searched_all:
            lines = ["규칙을 지키는 배정이 없음"] + explain_no_assignment(teams, unassigned)
            return None, "막힘: 규칙을 지키는 배정이 없음", lines
        lines = ["탐색 횟수 제한에 걸려 규칙을 지키는 배정을 끝까지 찾지 못함"]
        return None, "막힘: 규칙을 지키는 배정을 찾지 못했음", lines

    models = get_ai_models()
    api_key = get_secret("OPENROUTER_API_KEY")
    ai_assignment, log, used = run_ai_assignment(teams, unassigned, models, api_key, progress)

    if ai_assignment is not None:
        assignment = ai_assignment
        source = f"AI {used}차 모델"
    else:
        assignment = own_assignment
        source = "앱의 자체 배정(완전탐색)"
        log.append("AI 배정에 모두 실패해(또는 쓸 수 없어) 앱이 스스로 배정함")

    # 마지막으로 한 번 더 검사한다. (여기서 걸리면 프로그램 오류이므로 보여 주지 않는다)
    problems = validate_assignment(teams, unassigned, assignment)
    if problems:
        return None, "막힘: 배정안이 검사를 통과하지 못해 보여 줄 수 없음", log + problems

    lines = log + ["", f"배정안 ({source}, 5가지 검사 통과):"] + format_plan(teams, unassigned, assignment)
    plan = {"assignment": assignment, "source": source}
    return plan, f"승인: 배정안을 만들었음 ({source}). 내용을 확인하고 '배정안 확정'을 누르세요", lines


def confirm_assignment(conn, admin_student_no, assignment):
    """
    배정안을 확정해 DB 에 저장한다. (결과 단어, 설명) 을 돌려준다.
    확정 직전에, 지금 DB 의 상태로 5가지 검사를 다시 한다. (배정안을 만든 뒤 상태가 바뀌었을 수 있다)
    """
    with conn.cursor() as cur:
        require_admin(cur, admin_student_no)
        lock_all_teams(cur)

        if not is_recruitment_closed(cur):
            return "막힘", "모집이 마감되지 않았음"

        teams = load_team_state(cur)
        unassigned = load_unassigned(cur)
        problems = validate_assignment(teams, unassigned, assignment)
        if problems:
            return "막힘", "지금 상태와 맞지 않아 확정하지 않았음. AI 배정을 다시 하세요 (" + " / ".join(problems[:3]) + ")"

        for student_id, team_id in assignment.items():
            add_member(cur, team_id, student_id)

    return "승인", f"배정을 확정함 (학생 {len(assignment)}명을 팀에 넣었음)"


def run_admin_action(action):
    """관리자 동작을 실행하고 안내 문구를 돌려준다. 오류가 나도 비밀 값은 보여 주지 않는다."""
    try:
        word, text = run_db(action)
    except NotAdmin:
        return "막힘: 관리자만 쓸 수 있는 기능임"
    except (psycopg2.Error, NoFreeSlot):
        return "막힘: 데이터베이스 문제로 처리하지 못했음. 이전 상태는 그대로 남아 있음"
    return f"{word}: {text}"


# ---------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------
def show_missing_url_error():
    st.error("DATABASE_URL 값을 찾지 못했습니다.")
    st.markdown(
        """
**내 컴퓨터에서 실행 중이라면**
- `.env` 파일이 `app.py`와 **같은 폴더**에 있는지 확인하세요.
- 파일 이름이 정확히 `.env`인지 확인하세요. (`.env.txt`이면 안 됩니다)
- 파일 안에 `DATABASE_URL="..."` 한 줄이 있는지 확인하세요.
- `.env`를 고쳤다면 터미널에서 앱을 껐다가(`Ctrl + C`) 다시 실행하세요.

**배포한 앱이라면**
- Streamlit의 앱 설정(Secrets)에 `DATABASE_URL = "..."` 을 같은 이름으로 넣었는지 확인하세요.
"""
    )


def show_connection_error(error):
    st.error("데이터베이스에 연결하지 못했습니다.")
    st.markdown(
        """
아래를 순서대로 확인해 보세요.
1. `DATABASE_URL`이 Supabase에서 복사한 주소와 같은지 확인하세요.
   주소 안의 `[YOUR-PASSWORD]` 부분을 **실제 DB 비밀번호로 바꿨는지**, 따옴표 안에 빈칸 없이 붙여 넣었는지 봅니다.
2. DB 비밀번호에 `@`, `:`, `/` 같은 특수문자가 있으면 주소가 깨질 수 있습니다.
   이 경우 Supabase에서 특수문자가 없는 비밀번호로 바꾸고 주소도 다시 복사하세요.
3. Supabase 대시보드에서 프로젝트가 **일시정지(Paused)** 상태가 아닌지 확인하세요.
4. 인터넷 연결을 확인하세요.
"""
    )
    # 비밀 값이 들어 있을 수 있으므로, 자세한 오류 문장은 보여 주지 않고 오류 종류만 보여 준다.
    with st.expander("개발자용 정보"):
        st.write(f"오류 종류: {type(error).__name__}")
        st.caption("보안을 위해 자세한 오류 내용은 표시하지 않습니다.")


def show_admin_setup_status():
    """관리자 계정을 준비하고, 결과를 화면에 알린다."""
    try:
        prepare_admin_account()
    except AdminPasswordMissing:
        st.warning(
            "ADMIN_PASSWORD 값을 찾지 못해 관리자 계정을 준비하지 못했습니다. "
            "`.env`(또는 Streamlit Secrets)에 ADMIN_PASSWORD 를 넣고 앱을 다시 실행하세요. "
            "그 전에는 관리자로 로그인할 수 없습니다."
        )
        return
    except (psycopg2.Error, ValueError) as error:
        st.error("관리자 계정을 준비하지 못했습니다.")
        st.markdown(
            """
- `tf_students` 테이블의 구조가 `schema.sql`과 같은지 확인하세요.
  (특히 관리자는 주 역할이 비어 있어도 되어야 합니다.)
- ADMIN_PASSWORD 는 영문 기준 72글자 이하로 정하세요. (한글은 한 글자가 3칸을 차지합니다)
"""
        )
        with st.expander("개발자용 정보"):
            st.write(f"오류 종류: {type(error).__name__}")
            st.caption("보안을 위해 자세한 오류 내용은 표시하지 않습니다.")
        return

    st.caption("관리자 계정(학번 admin)이 준비되어 있습니다.")


def show_login_form():
    """학번과 비밀번호 입력 화면. (눌렀는지, 학번, 비밀번호) 를 돌려준다."""
    with st.form("login_form"):
        student_no = st.text_input("학번", key="login_student_no")
        password = st.text_input("비밀번호", type="password", key="login_password")
        submitted = st.form_submit_button("로그인", key="login_submit")
    return submitted, student_no, password


def show_result(message, details=None):
    """단추를 누른 결과 안내를 보여 준다. 첫 단어는 승인/대기/거절/막힘 중 하나."""
    if message:
        with st.container(key="result"):
            st.write(message)
            if details:
                # 학생 이름 등이 들어 있을 수 있으므로 서식 없이 그대로 보여 준다.
                st.text("\n".join(f"- {line}" for line in details))


def show_logged_in_view(profile):
    """로그인한 사람의 정보를 보여 주고, 학생과 관리자를 구분한다. 로그아웃 단추도 둔다."""
    role_label = "관리자" if profile["is_admin"] else "학생"

    with st.container(key="whoami"):
        st.write(f"{profile['name']} (학번 {profile['student_no']}) - {role_label}으로 로그인했습니다.")
        if not profile["is_admin"]:
            st.write(f"주 역할: {profile['main_role']}")
            sub_roles = ", ".join(profile["sub_roles"]) if profile["sub_roles"] else "없음"
            st.write(f"보조 역할: {sub_roles}")

    if profile["is_admin"]:
        st.info("관리자 화면: 명단 올리기 -> 모집 마감 -> AI 배정 -> 배정안 확정 순서로 진행합니다.")
    else:
        st.info(
            "팀 목록에서 지원할 팀을 고르세요. 내 팀에 지원이 들어오면 찬성 또는 거부로 투표할 수 있습니다. "
            "다른 학생의 지원이나 투표는 '새로 고침'을 눌러야 보입니다."
        )

    # 다른 사람이 한 지원이나 투표를 보려면 화면을 다시 그려야 한다. (과제 공고 3장, 쉬운 해결)
    # 단추를 누르면 Streamlit 이 화면을 다시 그리면서 DB에서 최신 내용을 읽는다.
    st.button("새로 고침", key="refresh")

    if st.button("로그아웃", key="logout"):
        st.session_state.pop("student_no", None)
        st.session_state["result_message"] = "승인: 로그아웃했습니다."
        st.rerun()


def run_student_action(action):
    """학생의 동작(지원, 투표)을 실행하고 안내 문구를 돌려준다. 오류가 나도 비밀 값은 보여 주지 않는다."""
    try:
        word, text = run_db(action)
    except (psycopg2.Error, NoFreeSlot):
        return "막힘: 데이터베이스 문제로 처리하지 못했습니다. 잠시 뒤 다시 시도하세요."
    return f"{word}: {text}"


def on_apply(student_id, team_id):
    """지원 단추의 동작. 화면을 다시 그리기 전에 실행되고, 결과 안내는 세션에 맡겨 둔다."""
    st.session_state["result_message"] = run_student_action(
        lambda conn: apply_to_team(conn, student_id, team_id)
    )


def on_vote(voter_id, application_id, vote):
    """찬성/거부 단추의 동작."""
    st.session_state["result_message"] = run_student_action(
        lambda conn: cast_vote(conn, voter_id, application_id, vote)
    )


def show_incoming_applications(incoming, voter_id, closed):
    """내 팀에 들어온 지원들을 보여 주고, 아직 투표하지 않았다면 찬성/거부 단추를 보여 준다."""
    if not incoming:
        return

    st.subheader("내 팀에 들어온 지원")
    for item in incoming:
        with st.container(border=True):
            sub_roles = ", ".join(item["sub_roles"]) if item["sub_roles"] else "없음"
            st.text(f"{item['name']} | 주 역할: {item['main_role']} | 보조 역할: {sub_roles}")
            st.write(f"투표 현황: 찬성 {item['yes_count']}명 / 팀원 {item['member_count']}명")

            if item["my_vote"]:
                # 한 번 투표하면 바꿀 수 없으므로 단추 대신 내 투표를 보여 준다.
                st.write(f"내 투표: {item['my_vote']}")
            else:
                col_yes, col_no = st.columns(2)
                with col_yes:
                    st.button(
                        "찬성",
                        key=f"vote_yes_{item['student_no']}",
                        disabled=closed,
                        on_click=on_vote,
                        args=(voter_id, item["application_id"], "찬성"),
                    )
                with col_no:
                    st.button(
                        "거부",
                        key=f"vote_no_{item['student_no']}",
                        disabled=closed,
                        on_click=on_vote,
                        args=(voter_id, item["application_id"], "거부"),
                    )


def show_team_list(profile):
    """학생 화면: 팀 목록, 지원 단추, 내 팀에 들어온 지원과 투표 단추."""
    st.subheader("팀 목록")

    try:
        teams, view = run_db(lambda conn: load_student_screen(conn, profile["id"]))
    except psycopg2.Error as error:
        st.error(
            "팀 목록을 불러오지 못했습니다. 잠시 뒤 새로 고침(F5) 해 주세요. "
            "계속되면 관리자에게 알려 주세요."
        )
        # 비밀 값이 들어 있을 수 있으므로, 자세한 오류 문장은 보여 주지 않고 오류 종류만 보여 준다.
        with st.expander("개발자용 정보"):
            st.write(f"오류 종류: {type(error).__name__}")
            st.caption("보안을 위해 자세한 오류 내용은 표시하지 않습니다.")
        return

    if not teams:
        st.info("아직 만들어진 팀이 없습니다. 관리자가 명단을 올리면 팀이 만들어집니다.")
        return

    def is_my_team(team):
        return any(member["student_id"] == profile["id"] for member in team["members"])

    my_team = next((team for team in teams if is_my_team(team)), None)
    pending = view["pending"]

    # 지원 단추를 숨기거나 비활성화해야 하는 경우 (과제 공고 2.8절)
    block_reason = None
    if view["closed"]:
        block_reason = "모집이 마감되어 지원할 수 없습니다."
    elif my_team is not None:
        block_reason = "이미 팀이 있어 다른 팀에 지원할 수 없습니다."
    elif pending is not None:
        block_reason = "결과를 기다리는 지원이 있어 다른 팀에 지원할 수 없습니다."

    if my_team is None:
        st.info("아직 팀이 없음")
    if pending is not None:
        pending_team = next((team for team in teams if team["id"] == pending["team_id"]), None)
        pending_name = pending_team["name"] if pending_team else "한 팀"
        st.info(f"내 지원: {pending_name}에 지원했고 팀원의 투표를 기다리는 중입니다.")
    if block_reason:
        st.caption(block_reason)

    show_incoming_applications(view["incoming"], profile["id"], view["closed"])

    for team in teams:
        members = team["members"]
        title = team["name"] + (" (내 팀)" if is_my_team(team) else "")

        with st.container(key=team_container_key(team), border=True):
            st.markdown(f"**{title}**")
            st.write(f"인원 {len(members)}/{TEAM_MAX_SIZE}명 (정원 최대 {TEAM_MAX_SIZE}명)")

            if members:
                lines = []
                for number, member in enumerate(members, start=1):
                    sub_roles = ", ".join(member["sub_roles"]) if member["sub_roles"] else "없음"
                    lines.append(
                        f"{number}. {member['name']} | 주 역할: {member['main_role']} | 보조 역할: {sub_roles}"
                    )
                # 학생 이름에 특수문자가 있어도 깨지지 않도록 서식 없이 그대로 보여 준다.
                st.text("\n".join(lines))
            else:
                st.write("아직 팀원이 없음")

            # 지원 단추. 막히는 이유 중 이미 팀이 있음, 결과를 기다리는 지원이 있음, 마감은 비활성화하고
            # 정원, 주 역할, 필수 포함 역할은 누른 뒤 "막힘: 이유"로 알려 준다.
            st.button(
                "이 팀에 지원",
                key=f"apply_{team_key_suffix(team)}",
                disabled=block_reason is not None,
                on_click=on_apply,
                args=(profile["id"], team["id"]),
            )


def show_admin_panel(profile):
    """
    관리자 전용: 명단 올리기 화면.
    단추를 눌렀으면 (안내 문구, 자세한 내용 목록) 을, 누르지 않았으면 (None, None) 을 돌려준다.
    """
    st.subheader("명단 올리기")
    st.write("학생 명단 CSV 파일과 팀 수를 넣고 '명단으로 처음 상태 만들기'를 누르세요.")
    st.warning(
        "주의: 이 단추를 누르면 지금까지의 지원, 투표, 팀원, 마감 표시와 기존 학생이 모두 지워지고 "
        "올린 명단으로 새로 만들어집니다. 관리자 계정은 남습니다."
    )

    uploaded_file = st.file_uploader("명단 CSV 파일", type=["csv"], key="admin_roster_file")
    team_count = st.number_input("팀 수", min_value=1, value=3, step=1, key="admin_team_count")

    if st.button("명단으로 처음 상태 만들기", key="admin_start"):
        return handle_roster_upload(profile["student_no"], uploaded_file, team_count)

    return None, None


def show_admin_flow_panel(profile):
    """
    관리자 전용: 모집 마감, AI 배정, 배정안 확정 단추와 진행 안내(assign_status).
    단추를 눌렀으면 (안내 문구, 자세한 내용 목록) 을, 누르지 않았으면 (None, None) 을 돌려준다.
    """
    st.subheader("모집 마감, AI 배정, 확정")
    st.write("순서: 1) 모집 마감  2) AI 배정  3) 배정안 확정")

    close_clicked = st.button("모집 마감", key="admin_close")
    assign_clicked = st.button("AI 배정", key="admin_assign")
    confirm_clicked = st.button("배정안 확정", key="admin_confirm")

    # 진행 안내는 이 칸 안에서 계속 바뀐다. (AI 를 기다리는 동안에도 화면에 보이도록 칸을 먼저 만든다)
    with st.container(key="assign_status"):
        status_slot = st.empty()

    def show_lines(lines):
        status_slot.text("\n".join(lines) if lines else "아직 배정안이 없음")

    message = None
    details = None

    if close_clicked:
        st.session_state.pop("assign_plan", None)
        st.session_state.pop("assign_report", None)
        message = run_admin_action(lambda conn: close_recruitment(conn, profile["student_no"]))

    elif assign_clicked:
        st.session_state.pop("assign_plan", None)
        plan, message, report = prepare_assignment(profile["student_no"], show_lines)
        if plan is not None:
            st.session_state["assign_plan"] = plan
        st.session_state["assign_report"] = report

    elif confirm_clicked:
        plan = st.session_state.get("assign_plan")
        if plan is None:
            message = "막힘: 확정할 배정안이 없음. 먼저 'AI 배정'을 누르세요"
        else:
            message = run_admin_action(
                lambda conn: confirm_assignment(conn, profile["student_no"], plan["assignment"])
            )
            if message.startswith("승인"):
                st.session_state.pop("assign_plan", None)
                st.session_state["assign_report"] = ["배정안을 확정했음. 아래 팀 목록에서 결과를 확인하세요."]

    show_lines(st.session_state.get("assign_report"))
    return message, details


def show_admin_overview():
    """관리자 화면 아래쪽: 팀이 없는 학생(unassigned)과 팀 목록(team_N, 지원 단추 없음)."""
    try:
        teams = run_db(load_teams)
        unassigned = run_db(load_unassigned_students)
    except psycopg2.Error as error:
        st.error("팀 정보를 불러오지 못했습니다. 잠시 뒤 새로 고침(F5) 해 주세요.")
        with st.expander("개발자용 정보"):
            st.write(f"오류 종류: {type(error).__name__}")
            st.caption("보안을 위해 자세한 오류 내용은 표시하지 않습니다.")
        return

    st.subheader("팀이 없는 학생")
    with st.container(key="unassigned"):
        if unassigned:
            # 학생 이름에 특수문자가 있어도 깨지지 않도록 서식 없이 그대로 보여 준다.
            st.text("\n".join(describe_person(person) for person in unassigned))
        else:
            st.write("없음")

    st.subheader("팀 목록")
    for team in teams:
        members = team["members"]
        with st.container(key=team_container_key(team), border=True):
            st.markdown(f"**{team['name']}**")
            st.write(f"인원 {len(members)}/{TEAM_MAX_SIZE}명 (정원 최대 {TEAM_MAX_SIZE}명)")
            if members:
                lines = []
                for number, member in enumerate(members, start=1):
                    sub_roles = ", ".join(member["sub_roles"]) if member["sub_roles"] else "없음"
                    lines.append(
                        f"{number}. {member['name']} | 주 역할: {member['main_role']} | 보조 역할: {sub_roles}"
                    )
                st.text("\n".join(lines))
            else:
                st.write("아직 팀원이 없음")


def main():
    st.title("팀 편성 웹 앱")
    st.write(
        "이 앱은 팀 프로젝트를 위한 팀을 편성하는 웹 앱입니다. "
        "학번과 비밀번호로 로그인하세요."
    )

    # 1) 데이터베이스 연결과 테이블 확인 (이전 단계에서 만든 기능)
    try:
        missing = check_tables()
    except DatabaseUrlMissing:
        show_missing_url_error()
        return
    except psycopg2.Error as error:
        show_connection_error(error)
        return
    except Exception as error:  # 예상하지 못한 오류도 비밀 값 없이 안내한다.
        show_connection_error(error)
        return

    st.success("데이터베이스에 연결되었습니다.")

    if missing:
        st.warning("아래 테이블이 데이터베이스에 없습니다: " + ", ".join(missing))
        return  # 테이블이 없으면 로그인을 할 수 없으므로 여기서 멈춘다.
    st.success("필요한 테이블 7개(tf_ 로 시작)를 모두 찾았습니다.")

    # 2) 관리자 계정 준비
    show_admin_setup_status()

    st.divider()

    # 3) 로그인 상태 확인
    #    로그인 상태는 "학번"만 세션에 기억해 두고, 화면을 그릴 때마다 DB에서 정보를 다시 읽는다.
    #    (명단을 다시 올려서 계정이 사라졌거나 바뀐 경우에도 정확하게 알 수 있다)
    message = st.session_state.pop("result_message", None)
    student_no = st.session_state.get("student_no")
    profile = None

    if student_no:
        try:
            profile = run_db(lambda conn: load_profile(conn, student_no))
        except psycopg2.Error:
            st.error("로그인 정보를 불러오지 못했습니다. 잠시 뒤 새로 고침(F5) 해 주세요.")
            return

        if profile is None:
            st.session_state.pop("student_no", None)
            message = "막힘: 계정을 찾을 수 없어 로그아웃되었습니다. 다시 로그인하세요."

    # 4) 로그인한 상태면 내 정보를, 아니면 로그인 화면을 보여 준다.
    if profile is not None:
        show_logged_in_view(profile)

        # profile 은 방금 DB에서 읽은 값이므로, 관리자 여부를 믿고 화면을 나눈다.
        if profile["is_admin"]:
            # 관리자: 명단 올리기(이전 단계 그대로) -> 모집 마감, AI 배정, 확정 -> 팀이 없는 학생과 팀 목록
            details = None
            admin_message, admin_details = show_admin_panel(profile)
            if admin_message:
                message, details = admin_message, admin_details
                if admin_message.startswith("승인"):
                    # 명단을 새로 올렸으므로 이전 배정안과 안내는 버린다.
                    st.session_state.pop("assign_plan", None)
                    st.session_state.pop("assign_report", None)
            flow_message, flow_details = show_admin_flow_panel(profile)
            if flow_message:
                message, details = flow_message, flow_details
            show_result(message, details)
            show_admin_overview()
        else:
            # 학생: 결과 안내 아래에 팀 목록을 보여 준다.
            show_result(message)
            show_team_list(profile)
        return

    st.subheader("로그인")
    submitted, typed_student_no, typed_password = show_login_form()

    if submitted:
        ok, message = handle_login(typed_student_no, typed_password)
        if ok:
            # 로그인 성공: 학번을 세션에 기억하고 화면을 다시 그린다.
            st.session_state["student_no"] = typed_student_no.strip()
            st.session_state["result_message"] = message
            st.rerun()

    show_result(message)


main()
