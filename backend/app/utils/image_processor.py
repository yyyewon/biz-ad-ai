import io
from PIL import Image
from rembg import remove

def remove_background_and_resize(image_bytes: bytes, target_size=(512, 512)) -> bytes:
    try:
        # 1. 입력받은 바이너리 데이터를 이미지 객체로 변환
        input_image = Image.open(io.BytesIO(image_bytes))
        
        # 2. rembg 라이브러리로 배경 제거 수행
        print("[AI 전처리] 배경 제거(누끼) 작업을 시작합니다...")
        output_image = remove(input_image)
        
        # 3. AI 가중치 모델 규격에 맞게 크기 변환 (기본 512x512)
        print(f"[AI 전처리] 이미지를 {target_size} 크기로 리사이징합니다.")
        output_image = output_image.resize(target_size)
        
        # 4. 처리된 이미지를 다시 바이너리(Bytes) 형태로 패킹하여 반환 (PNG 포맷으로 투명도 유지)
        buffer = io.BytesIO()
        output_image.save(buffer, format="PNG")
        
        print("[AI 전처리] 이미지 가공이 성공적으로 완료되었습니다!")
        return buffer.getvalue()

    except Exception as e:
        print(f"[AI 전처리 에러] 이미지 처리 중 오류 발생: {e}")
        raise e
