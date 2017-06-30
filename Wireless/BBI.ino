#include "BBI.h"

#include "spi.h"
#include <string.h>

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <FS.h>
#include <WebSocketsServer.h>
#include <Hash.h>
#include <ESPAsyncTCP.h>
#include <Ticker.h>
#include <WiFiUdp.h>
#include <ArduinoOTA.h>
#include <ESP8266mDNS.h>
#include <DNSServer.h>
#include <EEPROM.h>


WebSocketsServer webSocket = WebSocketsServer(81);
ESP8266WebServer server(80);
File fsUploadFile;

unsigned long connectingTime = 0;

uint8_t APConnectMode = 0;

char AP_SSID[34]     = "";
char AP_password[65] = "";

/* Soft AP network parameters */
IPAddress apIP(192, 168, 4, 1);
IPAddress netMsk(255, 255, 255, 0);
char station_password[65] = "";
char station_SSID[33] = "";

char localIP[16];
char redirectURL[27];
char redirectPage[256];
// DNS server
const byte DNS_PORT = 53;
DNSServer dnsServer;

char sChar;
char buffer[128];
String message;

void setup() {
	Serial.begin(115200);
	delay(100);

	spi_init(HSPI);
	spi_mode(HSPI, 1, 0); // trailing clock, low idle

	SPIFFS.begin();

	loadSettings();


	WiFi.mode(WIFI_AP_STA);

	/* Setup the DNS server redirecting all the domains to the apIP */
	Serial.println("Starting DNS ");
	dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
	dnsServer.start(DNS_PORT, "*", apIP);

	Serial.println("Starting softAP ");
	WiFi.softAPConfig(apIP, apIP, netMsk);
	WiFi.softAP(station_SSID, station_password);

	if (APConnectMode == AP_AUTOCONNECT){
		Serial.print("Connecting to ");
		Serial.println(AP_SSID);
		WiFi.begin(AP_SSID, AP_password);
		connectingTime = millis();
		while (WiFi.status() != WL_CONNECTED) {
			if ((millis() - connectingTime) > 10000) {
				WiFi.disconnect();
				break;
			}
			delay(500);
			Serial.print(".");
		}

		if (WiFi.status() == WL_CONNECTED) {
			Serial.println("");
			Serial.println("WiFi connected");
			Serial.println("IP address: ");
			Serial.println(WiFi.localIP());
		}
	} else {
		WiFi.disconnect();
	}

	ArduinoOTA.setHostname("");
	ArduinoOTA.onStart([]() {
		Serial.println("Start");
	});
	ArduinoOTA.onEnd([]() {
		Serial.println("\nEnd");
	});
	ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
		Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
	});
	ArduinoOTA.onError([](ota_error_t error) {
	Serial.printf("Error[%u]: ", error);
	if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
		else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
		else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
		else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
		else if (error == OTA_END_ERROR) Serial.println("End Failed");
	});
	ArduinoOTA.begin();

	webSocket.begin();
	webSocket.onEvent(webSocketEvent);

	//SERVER INIT
	//called when the url is not defined here
	//use it to load content from SPIFFS
	server.onNotFound([](){
	if(!handleFileRead(server.uri()))
		server.send(404, "text/plain", "FileNotFound");
	});
	server.begin();

	sprintf(localIP, "%d.%d.%d.%d", WiFi.softAPIP()[0], WiFi.softAPIP()[1], WiFi.softAPIP()[2], WiFi.softAPIP()[3] );
	sprintf(redirectURL, "%s/mobile.htm", localIP);
	sprintf(redirectPage, "<html><head></head><body><a href='http://%s'>%s</body>", localIP, localIP );

}

void loop() {

  	dnsServer.processNextRequest();
	ArduinoOTA.handle();
    webSocket.loop();
    server.handleClient();

    if (Serial.available()) {
    	message = Serial.readStringUntil('\n');
    	//sChar = Serial.read();

		//sprintf(buffer, "%c", sChar );
		webSocket.broadcastTXT(message);

    }
}

void resetSettings(){

	uint8_t mac[WL_MAC_ADDR_LENGTH];
	WiFi.softAPmacAddress(mac);
	char buffer[20];
	sprintf(buffer, "BladeBench - %X%X",  mac[WL_MAC_ADDR_LENGTH-2],  mac[WL_MAC_ADDR_LENGTH-1] );

	EEPROM.begin(256);
	for (int i = 0; i < 256; i++)  EEPROM.write(i, 0);
	EEPROM.put(0, "BBSettings");
	EEPROM.put(10, 0); // settings version number
	EEPROM.put(11, AP_CONNECT_DISABLED); // ap connect mode
	EEPROM.put(20, buffer); // station SSID
	EEPROM.put(52, "12345678"); // station password
	EEPROM.put(116, ""); // ap SSID
	EEPROM.put(148, ""); // ap password
	EEPROM.put(212, 15); // ap password

	EEPROM.end();
}

void saveSettings(){

	EEPROM.begin(256);

	EEPROM.put(11, APConnectMode); // ap connect mode
	EEPROM.put(20, station_SSID); // station SSID
	EEPROM.put(52, station_password); // station password
	EEPROM.put(116, AP_SSID); // ap SSID
	EEPROM.put(148, AP_password); // ap password

	// next byte 213

	EEPROM.end();
}

void sendSettings(uint8_t num){
	char buffer[128];

	sprintf(buffer, "dAPMode:%i", APConnectMode );
	webSocket.sendTXT(num, buffer);
	sprintf(buffer, "dstationSSID:%s", station_SSID );
	webSocket.sendTXT(num, buffer);
	sprintf(buffer, "dstationPass:%s", station_password );
	webSocket.sendTXT(num, buffer);
	sprintf(buffer, "dAPSSID:%s", AP_SSID );
	webSocket.sendTXT(num, buffer);
	sprintf(buffer, "dAPPass:%s", AP_password );
	webSocket.sendTXT(num, buffer);
}

void sendStatus(uint8_t num){
	char buffer[128];
	sprintf(buffer, "dAPstatus:%i", WiFi.status() );
	webSocket.sendTXT(num, buffer);
	if (WiFi.status() == WL_CONNECTED) {
		sprintf(buffer, "dAPIP:%d.%d.%d.%d", WiFi.localIP()[0], WiFi.localIP()[1], WiFi.localIP()[2], WiFi.localIP()[3] );
		webSocket.sendTXT(num, buffer);
	}
}

void loadSettings(){
	EEPROM.begin(256);

	char headMessage[12] = "";
	uint8_t settingsVersion = 0;

	for (int i = 0; i < 11; i++){
		headMessage[i] = EEPROM.read(i);
	}
	headMessage[11] = '\0';

	EEPROM.get( 10, settingsVersion );
	EEPROM.get( 11, APConnectMode );

	for (int i = 0; i < 32; i++){
		station_SSID[i] = EEPROM.read(i+20);
	}
	station_SSID[32] = '\0';
	for (int i = 0; i < 64; i++){
		station_password[i] = EEPROM.read(i+52);
	}
	station_password[64] = '\0';


	for (int i = 0; i < 32; i++){
		AP_SSID[i] = EEPROM.read(i+116);
	}
	AP_SSID[32] = '\0';
	for (int i = 0; i < 64; i++){
		AP_password[i] = EEPROM.read(i+148);
	}
	AP_password[64] = '\0';

	EEPROM.end();

	if (strcmp(headMessage, "BBSettings")  != 0) {
		Serial.println("invalid settings EEPROM, resetting");
		resetSettings();
		loadSettings();
		return;
	}

}

String getContentType(String filename){
  if(server.hasArg("download")) return "application/octet-stream";
  else if(filename.endsWith(".htm")) return "text/html";
  else if(filename.endsWith(".html")) return "text/html";
  else if(filename.endsWith(".css")) return "text/css";
  else if(filename.endsWith(".js")) return "application/javascript";
  else if(filename.endsWith(".png")) return "image/png";
  else if(filename.endsWith(".gif")) return "image/gif";
  else if(filename.endsWith(".jpg")) return "image/jpeg";
  else if(filename.endsWith(".ico")) return "image/x-icon";
  else if(filename.endsWith(".xml")) return "text/xml";
  else if(filename.endsWith(".pdf")) return "application/x-pdf";
  else if(filename.endsWith(".zip")) return "application/x-zip";
  else if(filename.endsWith(".gz")) return "application/x-gzip";
  return "text/plain";
}

bool handleFileRead(String path){
  Serial.println("handleFileRead: " + path);

  // android captive portal detection
  if(path.endsWith("/generate_204")){
	  //server.sendHeader("Location", "mobile.html", true);
	  Serial.print("sent redirect URL ");
	  Serial.println(redirectURL);
	  
	  server.send ( 307, "text/html", redirectPage);
	  return true;
  }
  if(path.endsWith("/")) path += "mobile.html";
  String contentType = getContentType(path);
  String pathWithGz = path + ".gz";
  if(SPIFFS.exists(pathWithGz) || SPIFFS.exists(path)){
    if(SPIFFS.exists(pathWithGz))
      path += ".gz";
    File file = SPIFFS.open(path, "r");
    size_t sent = server.streamFile(file, contentType);
    file.close();
    return true;
  }
  return false;
}

void webSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t lenght) {

    switch(type) {
        case WStype_DISCONNECTED:
        	Serial.printf("[%u] Disconnected!\n", num);
            break;
        case WStype_CONNECTED:
            {
                IPAddress ip = webSocket.remoteIP(num);
                Serial.printf("[%u] Connected from %d.%d.%d.%d url: %s\n", num, ip[0], ip[1], ip[2], ip[3], payload);
				
				// send message to client
				webSocket.sendTXT(num, "Connected");
            }
            break;
        case WStype_TEXT:
        	//Serial.printf("[%u] get Text: %s\n", num, payload);

			if (strcmp((char*)payload, "seep")  == 0) {
				saveSettings();
			}else if (strcmp((char*)payload, "getSettings")  == 0) {
					sendSettings(num);
			}else if (strcmp((char*)payload, "getStatus")  == 0) {
					sendStatus(num);
			}else if (strcmp((char*)payload, "reboot")  == 0) {
				ESP.restart();
				// reboot
			}else if (strncmp((char*)payload, "apc", 3)  == 0) {
				// connect to AP
			}else if (strncmp((char*)payload, "apdc", 4)  == 0) {
				// disconnect from AP
			}else if (strncmp((char*)payload, "sapn", 4)  == 0) {
				// set the AP name
				char *payloadData = (char*)payload + 4;
				if ( strlen(payloadData) > 32) {
					//error case
					return;
				}
				strcpy( AP_SSID, payloadData);
				saveSettings();
			}else if (strncmp((char*)payload, "sapp", 4)  == 0) {
				// set the AP password
				char *payloadData = (char*)payload + 4;
				if ( strlen(payloadData) > 64) {
					//error case
					return;
				}
				strcpy( AP_password, payloadData);
				saveSettings();
			}else if (strncmp((char*)payload, "sapm", 4)  == 0) {
				// set the AP mode
				char *payloadData = (char*)payload + 4;
				int mode = 0;
				mode = atoi(payloadData);
				APConnectMode = mode;
				Serial.print("set mode ");
				Serial.println(mode);
				saveSettings();
			}else if (strncmp((char*)payload, "sstn", 4)  == 0) {
				// set the station password
				char *payloadData = (char*)payload + 4;
				if ( strlen(payloadData) > 32) {
					//error case
					return;
				}
				strcpy( station_SSID, payloadData);
				saveSettings();
			}else if (strncmp((char*)payload, "sstp", 4)  == 0) {
				// set the station password
					char *payloadData = (char*)payload + 4;
					if ( strlen(payloadData) > 64) {
						//error case
						return;
					}
					strcpy( station_password, payloadData);
					saveSettings();
			} else if (strncmp((char*)payload, "<ping>", 4)  == 0) {
				webSocket.sendTXT(num, "pong");
			} else {
				Serial.print((char*)payload);
			}
			
            // send message to client
            // webSocket.sendTXT(num, "message here");

            // send data to all connected clients
            // webSocket.broadcastTXT("message here");
            break;
        case WStype_BIN:
        	Serial.printf("[%u] get binary lenght: %u\n", num, lenght);
            hexdump(payload, lenght);

            // send message to client
            // webSocket.sendBIN(num, payload, lenght);
            break;
    }

}

