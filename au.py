import streamlit as st
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="AI安全ナビ", layout="wide")
st.title("🗺️ AI安全ナビ（事故データ統合版）")

# --- 1. 事故データ・危険データの読み込み（キャッシュ化） ---
@st.cache_resource
def load_gpkg_data():
    try:
        gdf = gpd.read_file("Higashi-Yodogawa_2.gpkg")
        return gdf.unary_union
    except Exception:
        return None

@st.cache_data
def load_accident_data():
    accident_points = []
    try:
        df = pd.read_csv("honhyo_2024.csv", encoding="shift_jis", low_memory=False)
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
            accident_points.append((row['lng_calc'], row['lat_calc']))
    except Exception:
        pass
    return accident_points

@st.cache_data
def load_additional_accidents():
    additional_data = []
    content_dict = {'1': '死亡事故', '2': '重傷事故', '3': '軽傷事故', '4': '物損事故'}
    type_dict = {'1': '人対車両', '2': '正面衝突', '3': '追突', '4': '出会い頭衝突', '5': 'すれ違い', '6': '右折時衝突', '7': '左折時衝突', '8': '車両単独', '21': '踏切事故'}
    vehicle_dict = {'1': '乗用車', '2': '貨物車', '3': '特殊車', '4': '乗用車', '5': '軽自動車', '18': '🚲自転車', '25': '🚲自転車', '20': '🚶歩行者', '35': '🚶歩行者', '11': '二輪車', '12': '原付'}
    
    try:
        try:
            df = pd.read_csv("Osaka-Koutuu_2.csv", encoding="shift_jis", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv("Osaka-Koutuu_2.csv", encoding="utf-8", low_memory=False)

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
                except Exception:
                    return None

            df['lat_calc'] = df[lat_cols[0]].apply(flexible_latlng)
            df['lng_calc'] = df[lng_cols[0]].apply(flexible_latlng)

            has_type = '事故類型' in df.columns
            has_content = '事故内容' in df.columns
            has_year = '発生日時  年' in df.columns 
            col_a_type = next((c for c in df.columns if '当事者種別' in c and ('Ａ' in c or 'A' in c)), None)
            col_b_type = next((c for c in df.columns if '当事者種別' in c and ('Ｂ' in c or 'B' in c)), None)
            
            for _, row in df.dropna(subset=['lat_calc', 'lng_calc']).iterrows():
                lat, lng = row['lat_calc'], row['lng_calc']
                info_text = "<b>【事故情報】</b><br>"
                if has_year:
                    year = str(row.get('発生日時  年', '')).replace('.0', '')
                    info_text += f"発生年: 20{year}年<br>"
                if has_content:
                    c_code = str(row['事故内容']).replace('.0', '')
                    info_text += f"事故内容: {content_dict.get(c_code, f'不明({c_code})')}<br>"
                if has_type:
                    t_code = str(row['事故類型']).replace('.0', '')
                    info_text += f"事故類型: {type_dict.get(t_code, f'その他({t_code})')}<br>"
                if col_a_type and pd.notna(row[col_a_type]):
                    v_code = str(row[col_a_type]).replace('.0', '')
                    info_text += f"<br>当事者A: {vehicle_dict.get(v_code, f'車({v_code})')}"
                if col_b_type and pd.notna(row[col_b_type]):
                    v_code = str(row[col_b_type]).replace('.0', '')
                    info_text += f"<br>当事者B: {vehicle_dict.get(v_code, f'車({v_code})')}"

                additional_data.append((lng, lat, info_text))
    except Exception:
        pass
    return additional_data

risk_union = load_gpkg_data()
accident_points = load_accident_data()
additional_data = load_additional_accidents()

# --- 2. 検索エンジンとUI設定 ---
geolocator = Nominatim(user_agent="anshin_navi_app_v3")

st.markdown("**出発地と目的地を入力してください**")
col1, col2 = st.columns(2)
with col1:
    start_query = st.text_input("どこから（好きな場所・住所でOK）", value="上新庄駅")
with col2:
    end_query = st.text_input("どこへ（好きな場所・住所でOK）", value="大阪経済大学")

time_mode = st.radio("いまのじかん", ["ひる（交通安全優先）", "よる（防犯優先）"])
is_night = (time_mode == "よる（防犯優先）")

if st.button("ルートをさがす"):
    with st.spinner("場所を検索し、最適な地図データをダウンロード中..."):
        try:
            start_loc = geolocator.geocode(start_query)
            end_loc = geolocator.geocode(end_query)
            
            if not start_loc or not end_loc:
                st.error("場所が見つかりませんでした。住所や有名な建物の名前で試してください。")
                st.stop()
                
            start_coord = (start_loc.latitude, start_loc.longitude)
            end_coord = (end_loc.latitude, end_loc.longitude)
            
            dist_m = geodesic(start_coord, end_coord).meters
            if dist_m > 15000:
                st.warning("距離が15kmを超えています。サーバー負荷を避けるため、もう少し近い場所を指定してください。")
                st.stop()
                
            mid_lat = (start_coord[0] + end_coord[0]) / 2
            mid_lng = (start_coord[1] + end_coord[1]) / 2
            
            # その都度、必要な範囲だけ道路網をダウンロード
            G = ox.graph_from_point((mid_lat, mid_lng), dist=dist_m/2 + 500, network_type="all")
            
            # --- 3. AI安全コストの計算（事故データ・ポリゴンとの融合） ---
            for u, v, k, data in G.edges(keys=True, data=True):
                base_length = data.get("length", 10.0)
                risk_multiplier = 1.0
                highway_type = data.get("highway", "")
                geom = data.get("geometry")
                midpoint = geom.centroid if geom else Point(G.nodes[u]["x"], G.nodes[u]["y"])
                mid_x, mid_y = midpoint.x, midpoint.y
                
                # 夜間・大通りの基本判定
                if is_night and highway_type in ["residential", "living_street", "path", "unclassified"]:
                    risk_multiplier += 2.0 
                if highway_type in ["primary", "secondary", "trunk"] and not is_night:
                    risk_multiplier += 1.5
                
                # 危険ポリゴン（GPKG）の判定
                if risk_union is not None:
                    if risk_union.distance(midpoint) < 0.001:
                        risk_multiplier += 2.0
                            
                # 事故データ（CSV）の判定：道の上に事故ピンがあれば重みを増やす
                accident_risk = sum(1 for ax, ay in accident_points if abs(mid_x - ax) < 0.0005 and abs(mid_y - ay) < 0.0005)
                risk_multiplier += accident_risk

                data["safe_cost"] = base_length * risk_multiplier

            # --- 4. ルート探索 ---
            orig_node = ox.distance.nearest_nodes(G, start_coord[1], start_coord[0])
            dest_node = ox.distance.nearest_nodes(G, end_coord[1], end_coord[0])
            
            try:
                route_safe = nx.shortest_path(G, orig_node, dest_node, weight="safe_cost")
            except Exception:
                route_safe = []
            
            # --- 5. マップの描画 ---
            m = folium.Map(location=[mid_lat, mid_lng], zoom_start=15, tiles="OpenStreetMap")
            folium.Marker(start_coord, tooltip="出発", icon=folium.Icon(color="blue", icon="play")).add_to(m)
            folium.Marker(end_coord, tooltip="到着", icon=folium.Icon(color="red", icon="flag")).add_to(m)
            
            if route_safe:
                route_safe_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in route_safe]
                folium.PolyLine(route_safe_coords, color="green", weight=6, opacity=0.9, tooltip="AI安全ルート").add_to(m)
            
            # ダウンロードした地図の範囲内にある事故ピンだけを描画する
            # （重くならないよう、mid_lng, mid_lat周辺のみ）
            radius_deg = (dist_m/2 + 500) / 111000 # メートルを大まかな度数に変換
            
            for ax, ay in accident_points:
                if (mid_lng - radius_deg < ax < mid_lng + radius_deg) and (mid_lat - radius_deg < ay < mid_lat + radius_deg):
                    folium.CircleMarker([ay, ax], radius=3, color="red", fill=True, fill_opacity=0.7).add_to(m)

            for ax, ay, info in additional_data:
                if (mid_lng - radius_deg < ax < mid_lng + radius_deg) and (mid_lat - radius_deg < ay < mid_lat + radius_deg):
                    popup_html = folium.Popup(info, max_width=300)
                    folium.CircleMarker([ay, ax], radius=5, color="blue", fill=True, fill_opacity=0.9, popup=popup_html, tooltip="詳細を見る").add_to(m)
                    
            if risk_union is not None:
                folium.GeoJson(risk_union, style_function=lambda x: {'fillColor': 'orange', 'color': 'orange', 'weight': 1, 'fillOpacity': 0.3}).add_to(m)
            
            st_folium(m, width=800, height=500)
            st.success("ルート計算が完了しました！")
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")