"""비전 LLM에 보낼 한국어 프롬프트."""

CLASSIFY_PROMPT = """당신은 보험 청구 서류를 정리하는 보조입니다.
아래 번호가 붙은 사진들은 병원·약국에서 받은 서류(진단서, 소견서, 처방전, 진료비 영수증 등)를 찍은 것입니다.
같은 환자 + 같은 질병/사고에 속하는 서류끼리 그룹으로 묶어 주세요.
그룹 단서: 환자 이름, 진료(조제) 날짜, 진단명, 의료기관명.

반드시 아래 형태의 JSON 객체 하나만 출력하세요. 설명 글 금지.
{"groups":[{"patient":"환자 성명","claim_type":"상해 또는 질병","date":"YYYY-MM-DD(사고일 또는 진료 시작일)","diagnosis":"진단명 또는 사고 내용 요약","image_nos":[1,2]}]}

규칙:
- 모든 사진 번호는 정확히 하나의 그룹에만 속해야 합니다.
- 환자 이름이 판독되지 않으면 patient를 "알수없음"으로 적습니다.
- 서류에 사고·부상·다침 등 외부 요인이 보이면 claim_type은 "상해", 질병·증상·감염 등은 "질병"입니다. 약국 조제·복약 안내만 보이는 서류는 통상 "질병"입니다.
- diagnosis는 서류에 적힌 진단명原文을 우선 사용하되, 질병분류기호(예: H368, H400 등)만 있는 경우 해당 코드의 한국어 질병명을 함께 적어주세요 (예: 'H368(기타 망막장애), H400(녹내장의증)').
서류 목록:"""

EXTRACT_PROMPT = """보험금 청구 데이터를 추출합니다. 첨부된 사진들은 같은 청구 건의 서류들입니다.
(분류 단계 Hint: {hint})

반드시 아래 형태의 JSON 객체 하나만 출력하세요. 설명 글 금지.
{{"patient":"환자명","claim_type":"상해|질병","hospitalization":"입원|통원","treatment_start":"YYYY-MM-DD","treatment_end":"YYYY-MM-DD","diagnosis":"진단명","incident_desc":null,"incident_place":null,"incident_datetime":null}}

규칙:
- claim_type이 "상해"일 때만 incident_desc(사고 경위), incident_place(사고 장소), incident_datetime("YYYY-MM-DD HH:MM")를 채우고, "질병"이면 셋 다 null로 둡니다.
- hospitalization: 입원·수술·입원확인·입원일수 같은 문구가 있으면 "입원", 아니면 "통원".
- treatment_start/treatment_end: 서류에 보이는 치료·복약 기간의 시작과 끝. 같은 날 진료였다면 둘 같은 날짜.
- diagnosis: 서류에 적힌 진단명. 서류에 질병분류기호(예: H368, H400 등)만 기재된 경우 코드의 한국어 질병명을 함께 병기하세요 (예: 'H368(기타 망막장애), H400(녹내장의증)').
- 서류에서 찾을 수 없는 정보는 절대 추측하지 말고 null로 둡니다.
- 날짜는 반드시 YYYY-MM-DD 형식(시간 포함 시 YYYY-MM-DD HH:MM)."""
