from flask import Flask, jsonify, request
from flask_cors import CORS
import ibm_boto3
from ibm_botocore.client import Config, ClientError
import json
import http.client

# IBM Cloud Object Storage (COS) konfigurálása
cos = ibm_boto3.client(
    's3',
    ibm_api_key_id='5o6X835azJMALPLiebgIUUqRQ8e-NEM_PkQJ4thH9aI7',
    ibm_service_instance_id='f39973c6-786a-459c-9564-40f6d8e6a6b7',
    config=Config(signature_version='oauth'),
    endpoint_url='https://s3.us-south.cloud-object-storage.appdomain.cloud'  # Nyilvános végpont használata
)

bucket_name = 'servicenow3'  # COS bucket neve

# IBM WatsonX konfiguráció
ibm_cloud__iam_url = "iam.cloud.ibm.com"
ibm_watsonx_url = "us-south.ml.cloud.ibm.com"
ibm_watsonx_model_generation_api = "/ml/v1-beta/generation/text?version=2023-05-29"
apikey = "5o6X835azJMALPLiebgIUUqRQ8e-NEM_PkQJ4thH9aI7"
project_id = "55fd7a8e-f126-4253-92b2-52912c85b15a"

# Flask alkalmazás beállítása
app = Flask(__name__)
CORS(app)  # CORS engedélyezése a Flask alkalmazás számára

# Hozzáférési token lekérése az IBM Cloud IAM-től
def get_access_token():
    conn_ibm_cloud_iam = http.client.HTTPSConnection(ibm_cloud__iam_url)
    payload = "grant_type=urn%3Aibm%3Aparams%3Aoauth%3Agrant-type%3Aapikey&apikey=" + apikey
    headers = { 'Content-Type': "application/x-www-form-urlencoded" }
    conn_ibm_cloud_iam.request("POST", "/identity/token", payload, headers)
    res = conn_ibm_cloud_iam.getresponse()
    data = res.read()
    decoded_json = json.loads(data.decode("utf-8"))
    return decoded_json["access_token"]

# WatsonX API hívása
def watsonx_generate(payload, access_token):
    conn_watsonx = http.client.HTTPSConnection(ibm_watsonx_url)
    headers = {
        'Authorization': "Bearer " + access_token,
        'Content-Type': "application/json",
        'Accept': "application/json"
    }
    conn_watsonx.request("POST", ibm_watsonx_model_generation_api, payload, headers)
    res = conn_watsonx.getresponse()
    data = res.read()
    decoded_json = json.loads(data.decode("utf-8"))
    return decoded_json

# Payload létrehozása a WatsonX API-hoz
def create_payload(question, context):
    payload_json_flan_ul2 = {
        "model_id": "meta-llama/llama-3-1-70b-instruct",
        "input": context + "Input: " + question + " Output:",  # Egyetlen szóköz az "Output:" után
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": 20,
            "min_new_tokens": 0,
            "stop_sequences": ["\n", "  "],  # Stop szekvenciák hozzáadása az extra szöveg megakadályozására
            "repetition_penalty": 1
        },
        "project_id": project_id
    }

    str_payload = json.dumps(payload_json_flan_ul2)
    return str_payload

# Kontextus betöltése COS-ból
def load_context_from_cos():
    try:
        # Kontextus betöltése a context.txt fájlból COS-ban
        response = cos.get_object(Bucket=bucket_name, Key='context.txt')
        context = response['Body'].read().decode('utf-8')
        return context
    except ClientError as e:
        print(f"Hiba a kontextus betöltésekor a COS-ból: {e}")
        return None

# Új kérdés és válasz páros hozzáfűzése a naplófájlhoz a COS-ban
def append_to_log(question, answer):
    try:
        try:
            # Meglévő napló betöltése a COS-ból
            response = cos.get_object(Bucket=bucket_name, Key='csoportailog.txt')
            log_content = response['Body'].read().decode('utf-8')
        except ClientError as e:
            # Ha a fájl nem létezik, üres napló inicializálása
            if e.response['Error']['Code'] == 'NoSuchKey':
                log_content = ''
            else:
                raise e

        # Új bejegyzés formázása
        new_entry = f"\nInput: {question}\nOutput: {answer}\n"

        # Új bejegyzés hozzáadása a meglévő naplóhoz
        updated_log = log_content + new_entry

        # Frissített napló feltöltése vissza a COS-ba
        cos.put_object(Bucket=bucket_name, Key='csoportailog.txt', Body=updated_log.encode('utf-8'))
    except ClientError as e:
        print(f"Hiba a napló frissítésekor: {e}")

# Válasz lekérése egy adott kérdéshez
def getTopAnswer(question):
    try:
        access_token = get_access_token()  # Dinamikus hozzáférési token lekérése
        context = load_context_from_cos()  # Kontextus betöltése a COS-ból
        if not context:
            return "Hiba: Nem sikerült betölteni a kontextust."

        str_payload = create_payload(question, context)
        out_json = watsonx_generate(str_payload, access_token)
        answer = out_json["results"][0]['generated_text']

        # Kérdés és válasz hozzáfűzése a naplóhoz
        append_to_log(question, answer)

        return answer
    except Exception as e:
        print(f"Hiba a getTopAnswer függvényben: {e}")
        return "Hiba a kérés feldolgozása közben."

# Flask végpont a felhasználói lekérdezések kezelésére
@app.route('/get_answer', methods=['POST'])
def get_answer():
    data = request.get_json()  # JSON adatok lekérése a kérésből
    question = data.get("question")  # Kérdés kinyerése a bemenetből

    if question:
        # Válasz lekérése a megadott kérdés alapján
        answer = getTopAnswer(question)

        # Válasz tisztítása: szóközök és új sorok eltávolítása
        cleaned_answer = answer.strip()  # szóközök és új sorok eltávolítása

        return jsonify({"answer": cleaned_answer}), 200
    else:
        return jsonify({"error": "Nincs kérdés megadva"}), 400

if __name__ == '__main__':
    # Flask alkalmazás futtatása az 5000-es porton
    app.run(debug=True, host='0.0.0.0', port=5000)
