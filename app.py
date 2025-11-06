from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import requests
import urllib.parse
import re
from html.parser import HTMLParser
from datetime import datetime

load_dotenv()

app = Flask(__name__)

# ★ Supabase 설정 ★
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# API 키
SERVICE_KEY = os.getenv('SERVICE_KEY')
FOODQR_ACCESS_KEY = os.getenv('FOODQR_ACCESS_KEY')

# API URL
HACCP_API_URL = 'http://apis.data.go.kr/B553748/CertImgListServiceV3/getCertImgListServiceV3'
FOOD_QR_API_URL = 'https://foodqr.kr/openapi/service/qr1007/F007'

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
    },
    '닭': {
        'english': 'Chicken',
        'keywords': ['닭', '치킨', '닭고기', '가금류', '닭가슴살', '닭다리', '닭봉']
    }
}

print(f"\n{'='*60}")
print("Environment Check:")
print(f"SERVICE_KEY: {'✓ SET' if SERVICE_KEY else '✗ NOT SET'}")
print(f"FOODQR_ACCESS_KEY: {'✓ SET' if FOODQR_ACCESS_KEY else '✗ NOT SET'}")
print(f"SUPABASE_URL: {'✓ SET' if SUPABASE_URL else '✗ NOT SET'}")
print(f"SUPABASE_KEY: {'✓ SET' if SUPABASE_KEY else '✗ NOT SET'}")
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
    """Supabase에서 검색"""
    try:
        response = supabase.table('custom_products').select('*').or_(
            f"barcode.eq.{search_value},imrpt_no.eq.{search_value}"
        ).execute()
        
        if response.data and len(response.data) > 0:
            product = response.data[0]
            print(f"[Supabase] ✓ Found: {product['product_name']}")
            return {
                'source': 'Custom Database',
                'product': {
                    'prdctNm': product['product_name'],
                    'prvwCn': product['raw_materials']
                }
            }
        return None
    except Exception as e:
        print(f"[Supabase Error] {str(e)}")
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
    """Food QR API에서 검색"""
    
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
    
    for search_info in search_params_list:
        try:
            search_name = search_info['name']
            params = search_info['params']
            
            print(f"[FoodQR] Searching with {search_name}: {search_value}")
            
            response = requests.get(FOOD_QR_API_URL, params=params, timeout=15)
            
            print(f"[FoodQR] Status Code: {response.status_code}")
            
            if response.status_code != 200:
                print(f"[FoodQR] Failed with {response.status_code}")
                continue
            
            result = response.json()
            
            if result.get('response'):
                response_obj = result['response']
                
                if response_obj.get('body'):
                    body = response_obj['body']
                    
                    if body.get('items'):
                        items = body['items']
                        
                        if isinstance(items, dict):
                            if items.get('item'):
                                product = items['item']
                                
                                print(f"[FoodQR] ✓ Found using {search_name}")
                                
                                return {
                                    'source': 'FoodQR',
                                    'searchMethod': search_name,
                                    'product': product
                                }
                        
                        elif isinstance(items, list) and len(items) > 0:
                            product = items[0]
                            
                            if isinstance(product, dict) and product.get('item'):
                                product = product['item']
                            
                            print(f"[FoodQR] ✓ Found using {search_name}")
                            
                            return {
                                'source': 'FoodQR',
                                'searchMethod': search_name,
                                'product': product
                            }
            
            print(f"[FoodQR] No items found with {search_name}")
            
        except Exception as e:
            print(f"[FoodQR] Error with {search_name}: {str(e)}")
            continue
    
    print(f"[FoodQR] ✗ All search methods failed")
    return None

def extract_product_info_foodqr(product):
    """Food QR API 응답에서 제품 정보 추출"""
    
    product_name = product.get('prdctNm', 'Unknown Product')
    
    raw_html = product.get('prvwCn', '')
    
    raw_materials = strip_html(raw_html) if raw_html else ''
    
    print(f"[FoodQR Extract] Product Name: {product_name}")
    print(f"[FoodQR Extract] Raw Materials length: {len(raw_materials) if raw_materials else 0}")
    
    return product_name, raw_materials

@app.route('/test', methods=['GET'])
def test():
    """API 연결 테스트"""
    return jsonify({
        'status': 'ok',
        'SERVICE_KEY_set': SERVICE_KEY is not None,
        'FOODQR_ACCESS_KEY_set': FOODQR_ACCESS_KEY is not None,
        'SUPABASE_set': SUPABASE_URL is not None and SUPABASE_KEY is not None
    })

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
        # 1차: Supabase 검색 (가장 빠름!)
        print("[Search] Step 1: Searching Supabase...")
        supabase_result = search_custom_database(search_value)
        
        if supabase_result:
            product = supabase_result['product']
            product_name = product.get('prdctNm', 'Unknown')
            raw_materials = product.get('prvwCn', '')
            
            if raw_materials:
                found_ingredients = find_ingredients(raw_materials)
                return jsonify({
                    'productName': product_name,
                    'source': supabase_result['source'],
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

@app.route('/add-product', methods=['POST'])
def add_product():
    """Supabase에 제품 추가"""
    data = request.get_json()
    
    try:
        product_name = data.get('productName', '').strip()
        barcode = data.get('barcode', '').strip()
        imrpt_no = data.get('imrptNo', '').strip()
        raw_materials = data.get('rawMaterials', '').strip()
        
        if not product_name or not raw_materials:
            return jsonify({'error': 'Product name and raw materials required'}), 400
        
        if not barcode and not imrpt_no:
            return jsonify({'error': 'Barcode or imrptNo required'}), 400
        
        # Supabase에 저장
        response = supabase.table('custom_products').insert({
            'barcode': barcode if barcode else None,
            'imrpt_no': imrpt_no if imrpt_no else None,
            'product_name': product_name,
            'raw_materials': raw_materials
        }).execute()
        
        print(f"[Supabase] Product added: {product_name}")
        
        return jsonify({
            'status': 'success',
            'message': f'✓ "{product_name}" added successfully!'
        }), 201
        
    except Exception as e:
        print(f"[Supabase Error] {str(e)}")
        return jsonify({'error': f'Failed to add product: {str(e)}'}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=port)
