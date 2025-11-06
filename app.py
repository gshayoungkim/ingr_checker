from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
import requests
import urllib.parse
import re
from html.parser import HTMLParser
from datetime import datetime

load_dotenv()

app = Flask(__name__)

# ★ SQLite 데이터베이스 설정 ★
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///products.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
# 환경 변수에서 인증키 로드
SERVICE_KEY = os.getenv('SERVICE_KEY')
FOODQR_ACCESS_KEY = os.getenv('FOODQR_ACCESS_KEY')

# API URL
HACCP_API_URL = 'http://apis.data.go.kr/B553748/CertImgListServiceV3/getCertImgListServiceV3'
FOOD_QR_API_URL = 'https://foodqr.kr/openapi/service/qr1007/F007'
class CustomProduct(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100))
    imrptNo = db.Column(db.String(100))
    productName = db.Column(db.String(500), nullable=False)
    rawMaterials = db.Column(db.Text, nullable=False)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('barcode', 'imrptNo', name='uq_barcode_imrptno'),
    )

# 데이터베이스 초기화 (앱 시작 시)
with app.app_context():
    db.create_all()
    print("✓ Database initialized")

# 카테고리별 원재료 매핑
INGREDIENTS_TO_CHECK = {
    '소고기': {
        'english': 'Beef',
        'keywords': ['소고기', '쇠고기', '우육', '비프', '등심', '안심']
    },
    '돼지고기': {
        'english': 'Pork',
        'keywords': ['돼지고기', '돼지', '포크', '베이컨', '햄', '삼겹살', '목살', '라드']
    },
    '우유': {
        'english': 'Milk & Dairy',
        'keywords': ['우유', '유제품', '치즈', '버터', '생크림', '연유', '유당', '유청', '카제인', '분유', '유크림']
    },
    '닭': {
        'english': 'Chicken',
        'keywords': ['닭', '치킨', '닭고기', '가금류', '닭가슴살', '닭다리', '닭봉']
    },
    '땅콩': {
        'english': 'Peanut',
        'keywords': ['땅콩', '피넛', '땅콩버터']
    },
    '계란': {
        'english': 'Egg',
        'keywords': ['계란', '달걀', '난백', '난황', '전란']
    },
    '생선': {
        'english': 'Fish',
        'keywords': ['생선', '어류', '참치', '연어', '고등어', '멸치', '어분']
    },
    '갑각류': {
        'english': 'Crustaceans',
        'keywords': ['새우', '게', '랍스터', '크랩', '홍게', '킹크랩', '가재', '킹새우']
    }
}

# 앱 시작 시 환경 변수 확인
print(f"\n{'='*60}")
print("Environment Variables Check:")
print(f"SERVICE_KEY: {'✓ SET' if SERVICE_KEY else '✗ NOT SET'}")
print(f"FOODQR_ACCESS_KEY: {'✓ SET' if FOODQR_ACCESS_KEY else '✗ NOT SET'}")
print(f"{'='*60}\n")

class HTMLStripper(HTMLParser):
    """HTML 태그 제거"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return ''.join(self.text)

def strip_html(html_text):
    """HTML 태그 제거 함수"""
    if not html_text:
        return ''
    
    stripper = HTMLStripper()
    try:
        stripper.feed(html_text)
        return stripper.get_data().replace('\n', '').replace('  ', ' ').strip()
    except:
        # HTML 파싱 실패 시 정규표현식으로 처리
        text = re.sub(r'<[^>]+>', '', html_text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

def find_ingredients(raw_materials):
    """원재료명에서 해당하는 모든 원재료 검출"""
    found_ingredients = {}
    
    for category, data in INGREDIENTS_TO_CHECK.items():
        detected_keywords = []
        
        for keyword in data['keywords']:
            if keyword in raw_materials:
                detected_keywords.append(keyword)
        
        if detected_keywords:
            found_ingredients[category] = {
                'english': data['english'],
                'detected': detected_keywords
            }
    
    return found_ingredients

def search_custom_database(search_value):
    """로컬 SQLite 데이터베이스에서 검색"""
    try:
        product = CustomProduct.query.filter(
            (CustomProduct.barcode == search_value) | 
            (CustomProduct.imrptNo == search_value)
        ).first()
        
        if product:
            print(f"[CustomDB] Found: {product.productName}")
            return {
                'source': 'Custom Database',
                'product': {
                    'prdctNm': product.productName,
                    'prvwCn': product.rawMaterials
                }
            }
        return None
    except Exception as e:
        print(f"[CustomDB] Error: {str(e)}")
        return None


def search_haccp_api(search_value):
    """HACCP API에서 검색"""
    try:
        params = {
            'serviceKey': urllib.parse.unquote(SERVICE_KEY),
            'prdlstReportNo': search_value,
            'returnType': 'json',
            'numOfRows': 100,
            'pageNo': 1
        }
        
        print(f"[HACCP] Searching with product number: {search_value}")
        response = requests.get(HACCP_API_URL, params=params, timeout=15)
        
        print(f"[HACCP] Status Code: {response.status_code}")
        
        if response.status_code != 200:
            return None
        
        result = response.json()
        
        if result.get('body') and result['body'].get('items'):
            items = result['body']['items']
            
            if isinstance(items, dict):
                items = [items]
            
            first_item = items[0]
            
            if 'item' in first_item:
                product = first_item['item']
            else:
                product = first_item
            
            print(f"[HACCP] ✓ Found product: {product.get('prdlstNm', 'Unknown')}")
            
            return {
                'source': 'HACCP',
                'product': product
            }
        
        return None
        
    except Exception as e:
        print(f"[HACCP] Error: {str(e)}")
        return None

def search_foodqr_api(search_value):
    """Food QR API에서 검색 (imrptNo 우선)"""
    
    # imrptNo를 먼저 시도, 그 다음 brcdNo
    search_params_list = [
        {
            'name': 'product report number (imrptNo)',
            'params': {
                'accessKey': FOODQR_ACCESS_KEY,
                'numOfRows': 10,
                'pageNo': 1,
                '_type': 'json',
                'imrptNo': search_value
            }
        },
        {
            'name': 'barcode (brcdNo)',
            'params': {
                'accessKey': FOODQR_ACCESS_KEY,
                'numOfRows': 10,
                'pageNo': 1,
                '_type': 'json',
                'brcdNo': search_value
            }
        }
    ]
    
    # 나머지는 기존과 동일...

    
    for search_info in search_params_list:
        try:
            search_name = search_info['name']
            params = search_info['params']
            
            print(f"\n[FoodQR] Searching with {search_name}: {search_value}")
            
            response = requests.get(FOOD_QR_API_URL, params=params, timeout=15)
            
            print(f"[FoodQR] Status Code: {response.status_code}")
            
            if response.status_code != 200:
                print(f"[FoodQR] HTTP Error {response.status_code}")
                continue
            
            result = response.json()
            
            # Food QR API 응답 구조: response.body.items.item
            if result.get('response'):
                response_obj = result['response']
                
                if response_obj.get('body'):
                    body = response_obj['body']
                    
                    if body.get('items'):
                        items = body['items']
                        
                        # items가 단일 객체일 수도 있고 배열일 수도 있음
                        if isinstance(items, dict):
                            # 단일 item인 경우
                            if items.get('item'):
                                product = items['item']
                                
                                print(f"[FoodQR] ✓ Found using {search_name} (response.body.items.item)")
                                print(f"[FoodQR] Product: {product.get('prdctNm', 'Unknown')}")
                                
                                return {
                                    'source': 'FoodQR',
                                    'searchMethod': search_name,
                                    'product': product
                                }
                        
                        elif isinstance(items, list) and len(items) > 0:
                            # 배열인 경우
                            product = items[0]
                            
                            if isinstance(product, dict) and product.get('item'):
                                product = product['item']
                            
                            print(f"[FoodQR] ✓ Found using {search_name} (array structure)")
                            print(f"[FoodQR] Product: {product.get('prdctNm', 'Unknown')}")
                            
                            return {
                                'source': 'FoodQR',
                                'searchMethod': search_name,
                                'product': product
                            }
            
            print(f"[FoodQR] No items found with {search_name}")
            
        except Exception as e:
            print(f"[FoodQR] Error with {search_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"[FoodQR] ✗ All search methods failed")
    return None

def extract_product_info_foodqr(product):
    """Food QR API 응답에서 제품 정보 추출"""
    
    product_name = product.get('prdctNm', 'Unknown Product')
    
    # prvwCn (미리보기 내용) - HTML 포맷
    raw_html = product.get('prvwCn', '')
    
    # HTML에서 원재료 정보 추출
    raw_materials = strip_html(raw_html) if raw_html else ''
    
    print(f"[FoodQR Extract] Product Name: {product_name}")
    print(f"[FoodQR Extract] Raw Materials (stripped): {raw_materials[:200] if raw_materials else 'None'}")
    
    return product_name, raw_materials

@app.route('/test', methods=['GET'])
def test():
    """API 연결 테스트"""
    return jsonify({
        'status': 'ok',
        'SERVICE_KEY_set': SERVICE_KEY is not None,
        'FOODQR_ACCESS_KEY_set': FOODQR_ACCESS_KEY is not None
    })
@app.route('/add-product', methods=['POST'])
def add_product():
    """사용자가 직접 제품 정보 추가"""
    data = request.get_json()
    
    try:
        product_name = data.get('productName', '').strip()
        barcode = data.get('barcode', '').strip()
        imrptNo = data.get('imrptNo', '').strip()
        raw_materials = data.get('rawMaterials', '').strip()
        
        if not product_name or not raw_materials:
            return jsonify({'error': 'Product name and raw materials are required'}), 400
        
        if not barcode and not imrptNo:
            return jsonify({'error': 'Please provide barcode or imrptNo'}), 400
        
        # 중복 확인
        existing = CustomProduct.query.filter(
            (CustomProduct.barcode == barcode) if barcode else False |
            (CustomProduct.imrptNo == imrptNo) if imrptNo else False
        ).first()
        
        if existing:
            return jsonify({'error': 'Product already exists'}), 400
        
        # 새 제품 추가
        new_product = CustomProduct(
            barcode=barcode if barcode else None,
            imrptNo=imrptNo if imrptNo else None,
            productName=product_name,
            rawMaterials=raw_materials
        )
        
        db.session.add(new_product)
        db.session.commit()
        
        print(f"[DB] New product added: {product_name}")
        
        return jsonify({
            'status': 'success',
            'message': f'✓ "{product_name}" has been added to the database!',
            'product': {
                'productName': product_name,
                'barcode': barcode,
                'imrptNo': imrptNo
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"[DB Error] {str(e)}")
        return jsonify({'error': f'Failed to add product: {str(e)}'}), 500

@app.route('/get-all-products', methods=['GET'])
def get_all_products():
    """추가된 모든 제품 조회 (관리용)"""
    try:
        products = CustomProduct.query.all()
        return jsonify({
            'count': len(products),
            'products': [{
                'id': p.id,
                'productName': p.productName,
                'barcode': p.barcode,
                'imrptNo': p.imrptNo,
                'createdAt': p.createdAt.isoformat()
            } for p in products]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_product():
    data = request.get_json()
    search_value = data.get('searchValue', '').strip()
    
    print(f"\n{'='*60}")
    print(f"Search request: {search_value}")
    print(f"{'='*60}")
    
    if not search_value:
        return jsonify({'error': 'Please enter a product number or barcode'}), 400
    
    try:
        # 1차: 로컬 데이터베이스 검색 (가장 빠름!)
        print("[Search] Step 1: Searching Custom Database...")
        custom_result = search_custom_database(search_value)
        
        if custom_result:
            product = custom_result['product']
            product_name = product.get('prdctNm', 'Unknown')
            raw_materials = product.get('prvwCn', '')
            
            if raw_materials:
                found_ingredients = find_ingredients(raw_materials)
                return jsonify({
                    'productName': product_name,
                    'source': custom_result['source'],
                    'rawMaterials': raw_materials,
                    'foundIngredients': found_ingredients
                })
        
        # 2차: HACCP API 검색
        print("[Search] Step 2: Searching HACCP API...")
        haccp_result = search_haccp_api(search_value)
        
        if haccp_result:
            product = haccp_result['product']
            product_name = product.get('prdlstNm', 'Unknown Product')
            raw_materials = product.get('rawmtrl', '')
            
            if not raw_materials:
                return jsonify({
                    'productName': product_name,
                    'source': 'HACCP',
                    'foundIngredients': {},
                    'rawMaterials': 'No ingredient information available.',
                })
            
            found_ingredients = find_ingredients(raw_materials)
            return jsonify({
                'productName': product_name,
                'source': 'HACCP',
                'rawMaterials': raw_materials,
                'foundIngredients': found_ingredients
            })
        
        # 3차: Food QR API 검색
        print("[Search] Step 3: Searching Food QR API...")
        foodqr_result = search_foodqr_api(search_value)
        
        if foodqr_result:
            product = foodqr_result['product']
            search_method = foodqr_result.get('searchMethod', 'unknown')
            product_name, raw_materials = extract_product_info_foodqr(product)
            
            if not raw_materials:
                return jsonify({
                    'productName': product_name,
                    'source': f'Food QR (e-Label) - {search_method}',
                    'foundIngredients': {},
                    'rawMaterials': 'No ingredient information available.',
                })
            
            found_ingredients = find_ingredients(raw_materials)
            return jsonify({
                'productName': product_name,
                'source': f'Food QR (e-Label) - {search_method}',
                'rawMaterials': raw_materials,
                'foundIngredients': found_ingredients
            })
        
        print("[Search] All sources returned no results")
        return jsonify({'error': 'Product not found in any database.'}), 404
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'API request timeout. Please try again.'}), 504
    except Exception as e:
        print(f"[Search Error] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Server error'}), 500

@app.route('/test-foodqr-full', methods=['GET'])
def test_foodqr_full():
    """Food QR 전체 흐름 테스트"""
    
    test_value = '197202880024061'
    
    print(f"\n{'='*60}")
    print(f"[TEST] Starting full Food QR test with: {test_value}")
    print(f"{'='*60}")
    
    result = search_foodqr_api(test_value)
    
    if result:
        print(f"\n[TEST] ✓ Result found!")
        print(f"[TEST] Result keys: {result.keys()}")
        print(f"[TEST] Source: {result.get('source')}")
        print(f"[TEST] SearchMethod: {result.get('searchMethod')}")
        print(f"[TEST] Product type: {type(result.get('product'))}")
        print(f"[TEST] Product keys: {result.get('product', {}).keys() if isinstance(result.get('product'), dict) else 'N/A'}")
        
        # 데이터 추출
        product = result['product']
        product_name, raw_materials = extract_product_info_foodqr(product)
        
        print(f"\n[TEST] Extraction complete:")
        print(f"[TEST] Product Name: {product_name}")
        print(f"[TEST] Raw Materials length: {len(raw_materials)}")
        
        # 원재료 검출
        found_ingredients = find_ingredients(raw_materials)
        
        print(f"[TEST] Found ingredients: {list(found_ingredients.keys())}")
        
        return jsonify({
            'status': 'success',
            'productName': product_name,
            'rawMaterialsLength': len(raw_materials),
            'foundIngredientsCount': len(found_ingredients),
            'foundIngredients': found_ingredients
        })
    else:
        print(f"\n[TEST] ✗ No result found")
        return jsonify({'status': 'failed'}), 404
@app.route('/test-raw-materials', methods=['GET'])
def test_raw_materials():
    """원재료 텍스트 확인"""
    
    test_value = '197202880024061'
    result = search_foodqr_api(test_value)
    
    if result:
        product = result['product']
        product_name, raw_materials = extract_product_info_foodqr(product)
        
        print(f"\n{'='*60}")
        print("[RAW MATERIALS] Full text:")
        print(raw_materials)
        print(f"{'='*60}\n")
        
        # 한 글자씩 검색해보기
        test_keywords = ['설탕', '고추장', '소고기', '돼지', '우유', '대두', '계란', '밀']
        
        print("[KEYWORD CHECK]")
        for keyword in test_keywords:
            found = keyword in raw_materials
            print(f"  '{keyword}': {found}")
        
        return jsonify({
            'productName': product_name,
            'rawMaterials': raw_materials,
            'rawMaterialsLength': len(raw_materials),
            'keywordChecks': {kw: kw in raw_materials for kw in test_keywords}
        })
    
    return jsonify({'status': 'failed'}), 404


if __name__ == '__main__':
    import os
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
