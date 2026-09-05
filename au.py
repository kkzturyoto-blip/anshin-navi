import streamlit as st
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point
from streamlit_js_eval import get_geolocation
from linebot import LineBotApi
from linebot.models import TextSendMessage
from geopy.geocoders import Nominatim # 🌟 検索を賢くする新しいライブラリ

# --- LINE Messaging API 設定 ---
LINE_CHANNEL_ACCESS_TOKEN = "zCEBhsxL1HAGvd/aya5Y3YwjGdM6/4dRkgHd2x8pAo0J1PPUQFnUKHxY1TYbAp6+OvtXAsEA5Y1q38sByofUJ+j/f+uwLl98jT7oLY0hjHKctQ/03Panvwse4Yq4UYz/hkM7KdPrq6j26jbS8hGi+QdB04t89/1O/w1cDnyilFU="
PARENT_USER_ID = "U2eaeb9a452069c590b21fe474a92e284"
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_line_message(message_text):
    try:
        line_bot_api.push_message(PARENT_USER_ID, TextSendMessage(text=message_text))
        return True
    except Exception as e:
        st.error(f"LINE通知に失敗しました: {e}")
        return False

# 🌟 新しい検索エンジン（ジオコーダー）の準備
geolocator = Nominatim(user_agent="anshin_navi_app")

st.set_page_config(page_title="あんしんナビ", layout="wide")
st.title("🚲 東淀川区 AIあんしんナビ")

@st.cache_resource
def load_map_data():
    G = ox.graph_from_place("Higashiyodogawa-ku, Osaka, Japan", network_type="all")
    try:
        gdf = gpd.read_file("Higashi-Yodogawa_2.gpkg")
        risk_union = gdf.unary_union
    except Exception:
        risk_union = None
    return G, risk_union

@st.cache_data
def load_risk_data(csv_path="honhyo_2024.csv"):
    accident_points = []
    try:
        df = pd.read_csv(csv_path, encoding="shift_jis", low_memory=False)
        if '都道府県コード' in df.columns:
            df = df[df['都道府県コード'] == 62]
        def convert_police_latlng(val):
            if pd.isna(val): return None
            val_str = str(int(val)).zfill(9) 
            degree = float(val_str[:2])
            minute = float(val_str[2:4])
            second = float(val_str[4:6]) + float(val_str[6:]) / 1000.0
            return degree + (minute / 60.0) + (second / 3600.0)
        lat_col = [col for col in df.columns if '緯度' in col][0]
        lng_col = [col for col in df.columns if '経度' in col][0]
        df['lat_calc'] = df[lat_col].apply(convert_police_latlng)
        df['lng_calc'] = df[lng_col].apply(convert_police_latlng)
        for _, row in df.dropna(subset=['lat_calc', 'lng_calc']).iterrows():
            lat, lng = row['lat_calc'], row['lng_calc']
            if 135.51 < lng < 135.56 and 34.73 < lat < 34.76:
                accident_points.append((lng, lat))
    except Exception:
        pass
    return accident_points

@st.cache_data
def load_additional_csv(csv_path="Osaka-Koutuu_2.csv"):
    additional_data = []
    # (前回と同じ事故情報読み込みロジック...省略せずにすべて記載します)
    content_dict = {'1': '死亡事故', '2': '重傷事故', '3': '軽傷事故', '4': '物損事故'}
    type_dict = {'1': '人対車両', '2': '正面衝突', '3': '追突', '4': '出会い頭衝突', '5': 'すれ違い', '6': '右折時衝突', '7': '左折時衝突', '8': '車両単独', '21': '踏切事故'}
    vehicle_dict = {'1': '乗用車', '2': '貨物車', '3': '特殊車', '4': '乗用車', '5': '軽自動車', '18': '🚲自転車', '25': '🚲自転車', '20': '🚶歩行者', '35': '🚶歩行者', '11': '二輪車', '12': '原付'}
    try:
        try:
            df = pd.read_csv(csv_path, encoding="shift_jis", low_memory=False)
        except:
            df = pd.read_csv(csv_path, encoding="utf-8", low_memory=False)
        lat_cols = [col for col in df.columns if '緯度' in col or 'lat' in col.lower() or 'y' in col.lower()]
        lng_cols = [col for col in df.columns if '経度' in col or 'lon' in col.lower() or 'lng' in col.lower() or 'x' in col.lower()]
        if lat_cols and lng_cols:
            def flexible_latlng(val):
                if pd.isna(val): return None
                try:
                    v = float(val)
                    if v > 1000:
                        val_str = str(int(v)).zfill(9)
                        degree = float(val_str[:2])
                        minute = float(val_str[2:4])
                        second = float(val_str[4:6]) + float(val_str[6:]) / 1000.0
                        return degree + (minute / 60.0) + (second / 3600.0)
                    return v
                except: return None
            df['lat_calc'] = df[lat_cols[0]].apply(flexible_latlng)
            df['lng_calc'] = df[lng_cols[0]].apply(flexible_latlng)
            has_type = '事故類型' in df.columns
            has_content = '事故内容' in df.columns
            has_year = '発生日時  年' in df.columns 
            col_a_type = next((c for c in df.columns if '当事者種別' in c and ('Ａ' in c or 'A' in c)), None)
            col_b_type = next((c for c in df.columns if '当事者種別' in c and ('Ｂ' in c or 'B' in c)), None)
            for _, row in df.dropna(subset=['lat_calc', 'lng_calc']).iterrows():
                lat, lng = row['lat_calc'], row['lng_calc']
                if 135.51 < lng < 135.56 and 34.73 < lat < 34.76:
                    info_text = "<b>【事故情報】</b><br>"
                    if has_year: info_text += f"発生年: 20{str(row.get('発生日時  年', '')).replace('.0', '')}年<br>"
                    if has_content: info_text += f"内容: {content_dict.get(str(row['事故内容']).replace('.0', ''), '不明')}<br>"
                    if has_type: info_text += f"類型: {type_dict.get(str(row['事故類型']).replace('.0', ''), '不明')}<br>"
                    additional_data.append((lng, lat, info_text))
    except Exception as e:
        st.warning(f"追加CSV読込失敗: {e}")
    return additional_data

G, risk_union = load_map_data()
accident_points = load_risk_data()
additional_data = load_additional_csv()

st.markdown("### 📞 ほごしゃへのれんらく")
if st.button("🚨 SOS（たすけて）", type="primary"):
    send_line_message("🚨【緊急】お子様がSOSボタンを押しました！至急、現在地を確認してください。")
    st.success("保護者へSOSを送信しました。")

st.markdown("### 📍 現在地の取得")
use_gps = st.checkbox("GPSをオンにして現在地を取得する")
current_location = None

if use_gps:
    loc = get_geolocation()
    if loc is not None:
        current_lat, current_lng = loc['coords']['latitude'], loc['coords']['longitude']
        current_location = (current_lat, current_lng)
        st.success("✅ 現在地を取得しました！")
        min_distance = 999
        closest_info = ""
        for ax, ay, info in additional_data:
            dist = ((current_lat - ay)**2 + (current_lng - ax)**2)**0.5
            if dist < min_distance:
                min_distance = dist
                closest_info = info
        if min_distance < 0.0003:
            st.error("🛑【ストップ！】危険な交差点が近づいています！")
            send_line_message(f"⚠️【自動通知】お子様が危険地点に接近しました。\n{closest_info.replace('<br>', ' ')}")

# 🌟 より柔軟な検索ボックス（プレースホルダーを変更）
with st.form(key="route_form"):
    col1, col2 = st.columns(2)
    with col1:
        default_start = "現在地" if use_gps and current_location else "大阪市東淀川区豊里2丁目"
        start_query = st.text_input("どこから（好きな場所・住所でOK）", value=default_start)
    with col2:
        end_query = st.text_input("どこへ（好きな場所・住所でOK）", value="大阪経済大学")

    time_mode = st.radio("いまのじかん", ["ひる（交通安全優先）", "よる（防犯優先）"])
    is_night = (time_mode == "よる（防犯優先）")
    submit_button = st.form_submit_button("ルートをさがす")

if "generated_map" not in st.session_state:
    st.session_state.generated_map = None

if submit_button:
    with st.spinner("AIが指定された場所と安全ルートを計算中..."):
        try:
            # 🌟 柔軟なキーワードから緯度経度を取得する新しい関数
            def get_latlng(query):
                if query == "現在地" and current_location:
                    return current_location
                # まずgeopyで検索（日本の細かい住所に強い）
                location = geolocator.geocode(query)
                if location:
                    return (location.latitude, location.longitude)
                # 見つからなければOSMnxで検索
                return ox.geocode(query)

            start_coord = get_latlng(start_query)
            end_coord = get_latlng(end_query)
            
            for u, v, k, data in G.edges(keys=True, data=True):
                base_length = data.get("length", 10.0)
                risk_multiplier = 1.0
                highway_type = data.get("highway", "")
                geom = data.get("geometry")
                midpoint = geom.centroid if geom else Point(G.nodes[u]["x"], G.nodes[u]["y"])
                
                if is_night and highway_type in ["residential", "living_street", "path", "unclassified"]:
                    risk_multiplier += 3.0
                if highway_type in ["primary", "secondary"] and not is_night:
                    risk_multiplier += 1.5
                if risk_union is not None and risk_union.distance(midpoint) < 0.001:
                    risk_multiplier += 2.0
                            
                accident_risk = sum(1 for ax, ay in accident_points if abs(midpoint.x - ax) < 0.0005 and abs(midpoint.y - ay) < 0.0005)
                risk_multiplier += accident_risk
                data["safe_cost"] = base_length * risk_multiplier

            orig_node = ox.distance.nearest_nodes(G, start_coord[1], start_coord[0])
            dest_node = ox.distance.nearest_nodes(G, end_coord[1], end_coord[0])
            
            try:
                route_safe = nx.shortest_path(G, orig_node, dest_node, weight="safe_cost")
            except:
                route_safe = []
            
            mid_lat, mid_lng = (start_coord[0] + end_coord[0]) / 2, (start_coord[1] + end_coord[1]) / 2
            m = folium.Map(location=[mid_lat, mid_lng], zoom_start=15, tiles="cartodbpositron")
            
            if route_safe:
                route_safe_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in route_safe]
                folium.PolyLine(route_safe_coords, color="green", weight=6, opacity=0.9, tooltip="あんしんルート").add_to(m)
            
            folium.Marker(start_coord, tooltip="出発地", icon=folium.Icon(color="blue", icon="play")).add_to(m)
            folium.Marker(end_coord, tooltip="目的地", icon=folium.Icon(color="red", icon="flag")).add_to(m)
            
            for ax, ay in accident_points:
                if (mid_lng - 0.02 < ax < mid_lng + 0.02) and (mid_lat - 0.02 < ay < mid_lat + 0.02):
                    folium.CircleMarker([ay, ax], radius=3, color="red", fill=True, fill_opacity=0.7).add_to(m)

            for ax, ay, info in additional_data:
                if (mid_lng - 0.02 < ax < mid_lng + 0.02) and (mid_lat - 0.02 < ay < mid_lat + 0.02):
                    folium.CircleMarker([ay, ax], radius=5, color="blue", fill=True, fill_opacity=0.9, popup=folium.Popup(info, max_width=300)).add_to(m)
                    
            if risk_union is not None:
                folium.GeoJson(risk_union, style_function=lambda x: {'fillColor': 'orange', 'color': 'orange', 'weight': 1, 'fillOpacity': 0.3}).add_to(m)
            
            st.session_state.generated_map = m
            
        except Exception as e:
            st.error(f"場所が見つかりませんでした。少し大きな目印や住所を入力してみてください: {e}")

if st.session_state.generated_map is not None:
    st_folium(st.session_state.generated_map, width=800, height=500, returned_objects=[])