-- =====================================================================
-- schema.sql : 팀 편성 웹 앱의 DB 테이블 (Supabase / PostgreSQL)
--
-- * 모든 테이블 이름은 tf_ 로 시작한다 (6장 실습 테이블과 구분하기 위함).
-- * 과제 공고 5장 "DB 최소 참고안"을 기준으로 만들었다.
-- * 이 파일은 "새 DB에 처음 한 번" 실행하는 용도이다.
--   이미 만든 테이블이 있으면 "already exists" 오류가 나는 것이 정상이다.
-- =====================================================================

-- 역할 6개: 기획자, 웹 프로그래머, 프론트엔드 디자이너, 테스터, 보고서 작성자, 발표자


-- ---------------------------------------------------------------------
-- 1) 학생과 관리자
--    - student_no : 학번 (유일). 관리자는 학번이 admin
--    - password_hash : 비밀번호를 해시(되돌릴 수 없는 문자열)로 바꿔 저장
--    - 관리자는 주 역할이 없으므로 main_role 이 비어 있고, 학생은 6개 역할 중 하나여야 함
-- ---------------------------------------------------------------------
create table tf_students (
    id            bigint generated always as identity primary key,
    student_no    text    not null unique,
    name          text    not null,
    main_role     text,
    password_hash text    not null,
    is_admin      boolean not null default false,
    constraint tf_students_main_role_check check (
        (is_admin and main_role is null)
        or
        (not is_admin and coalesce(main_role in (
            '기획자', '웹 프로그래머', '프론트엔드 디자이너',
            '테스터', '보고서 작성자', '발표자'
        ), false))
    )
);


-- ---------------------------------------------------------------------
-- 2) 보조 역할 (학생 1명에 0~2행)
-- ---------------------------------------------------------------------
create table tf_student_sub_roles (
    student_id bigint not null references tf_students(id) on delete cascade,
    role       text   not null,
    primary key (student_id, role),
    constraint tf_student_sub_roles_role_check check (role in (
        '기획자', '웹 프로그래머', '프론트엔드 디자이너',
        '테스터', '보고서 작성자', '발표자'
    ))
);


-- ---------------------------------------------------------------------
-- 3) 팀 (팀1, 팀2, ...)
-- ---------------------------------------------------------------------
create table tf_teams (
    id   bigint generated always as identity primary key,
    name text not null unique
);


-- ---------------------------------------------------------------------
-- 4) 팀원
--    - (team_id, slot_no) 가 기본 키 : 같은 팀의 같은 자리에는 한 명만 기록됨
--      (마지막 자리에 두 명이 동시에 들어와도 먼저 도착한 학생만 기록)
--    - slot_no 는 1~4 : 다섯 번째 자리를 막음
--    - student_id 는 유일 : 한 학생은 한 팀에만 소속
-- ---------------------------------------------------------------------
create table tf_members (
    team_id    bigint  not null references tf_teams(id) on delete cascade,
    slot_no    integer not null check (slot_no between 1 and 4),
    student_id bigint  not null unique references tf_students(id) on delete cascade,
    primary key (team_id, slot_no)
);


-- ---------------------------------------------------------------------
-- 5) 지원
--    - status : 대기 / 승인 / 거절
--    - reason : 거절 이유 등을 적는 칸 (비워도 됨)
-- ---------------------------------------------------------------------
create table tf_applications (
    id         bigint generated always as identity primary key,
    team_id    bigint      not null references tf_teams(id) on delete cascade,
    student_id bigint      not null references tf_students(id) on delete cascade,
    status     text        not null default '대기',
    reason     text,
    created_at timestamptz not null default now(),
    constraint tf_applications_status_check check (status in ('대기', '승인', '거절'))
);
CREATE UNIQUE INDEX tf_one_pending_application
ON public.tf_applications (student_id)
WHERE status = '대기';


-- ---------------------------------------------------------------------
-- 6) 투표
--    - (application_id, voter_id) 가 기본 키 : 한 번 투표하면 바꿀 수 없음
-- ---------------------------------------------------------------------
create table tf_votes (
    application_id bigint not null references tf_applications(id) on delete cascade,
    voter_id       bigint not null references tf_students(id) on delete cascade,
    vote           text   not null,
    primary key (application_id, voter_id),
    constraint tf_votes_vote_check check (vote in ('찬성', '거부'))
);


-- ---------------------------------------------------------------------
-- 7) 설정 (모집 마감 여부 등)
-- ---------------------------------------------------------------------
create table tf_settings (
    key   text primary key,
    value text
);