import os
import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, timedelta, timezone

# --- CONFIGURATION ---
app = Flask(__name__)

# Use environment variable for API Key for security
OPENWEATHERMAP_API_KEY = os.environ.get('OPENWEATHERMAP_API_KEY', 'cf08fdc54e16926861f2f8730d188a65')
OPENWEATHERMAP_API_URL = "http://api.openweathermap.org/data/2.5/weather"
OPENWEATHERMAP_FORECAST_URL = "http://api.openweathermap.org/data/2.5/forecast"
# NEW: Air Pollution API URL
OPENWEATHERMAP_AIR_POLLUTION_URL = "http://api.openweathermap.org/data/2.5/air_pollution"

# --- HELPER FUNCTIONS (JINJA FILTERS) ---

def time_from_utc(utc_timestamp, timezone_offset):
    """
    Converts a UTC timestamp and timezone offset (in seconds) to a localized 12-hour time string.
    Example: 06:30 AM
    """
    # Create the timezone object from the offset
    tz = timezone(timedelta(seconds=timezone_offset))
    
    # Convert UTC timestamp to localized datetime object
    utc_dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    local_dt = utc_dt.astimezone(tz)
    
    # Format to 12-hour time (e.g., 06:15 AM)
    return local_dt.strftime('%I:%M %p')

def day_from_dt(dt_txt):
    """
    Extracts the day name (e.g., Mon) from OpenWeatherMap's dt_txt format.
    """
    dt = datetime.strptime(dt_txt, '%Y-%m-%d %H:%M:%S')
    return dt.strftime('%a')

# Register the time_from_utc function as a global Jinja function
app.jinja_env.globals.update(time_from_utc=time_from_utc)
app.jinja_env.globals.update(day_from_dt=day_from_dt)


# --- MAIN ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def index():
    weather = None
    error = None
    city = None
    hourly_forecast = None
    daily_forecast = None
    # NEW: Air Quality Index variable
    air_quality = None

    if request.method == 'POST':
        city = request.form['city'].strip()
        if not city:
            error = "Please enter a city name."
            return render_template('index.html', error=error)

        try:
            # 1. Get Current Weather Data
            weather_response = requests.get(OPENWEATHERMAP_API_URL, params={
                'q': city,
                'appid': OPENWEATHERMAP_API_KEY,
                'units': 'metric'
            })
            weather_data = weather_response.json()

            if weather_data['cod'] == 200:
                weather = weather_data
                
                # Extract Lat/Lon for AQI call
                lat = weather_data['coord']['lat']
                lon = weather_data['coord']['lon']

                # 3. Get Air Quality Index (AQI) Data
                air_pollution_response = requests.get(OPENWEATHERMAP_AIR_POLLUTION_URL, params={
                    'lat': lat,
                    'lon': lon,
                    'appid': OPENWEATHERMAP_API_KEY
                })
                air_pollution_data = air_pollution_response.json()
                
                if air_pollution_data and 'list' in air_pollution_data:
                    # The main AQI data is in the first list item
                    air_quality_data = air_pollution_data['list'][0]
                    aqi_value = air_quality_data['main']['aqi']
                    
                    # Convert AQI integer (1-5) to descriptive text
                    aqi_desc = {
                        1: "Good",
                        2: "Fair",
                        3: "Moderate",
                        4: "Poor",
                        5: "Very Poor"
                    }.get(aqi_value, "N/A")
                    
                    air_quality = {
                        'aqi': aqi_value,
                        'description': aqi_desc
                    }
                
            else:
                error = f"City not found: {city}"
                return render_template('index.html', error=error)

            # 2. Get 5-Day / 3-Hour Forecast Data
            forecast_response = requests.get(OPENWEATHERMAP_FORECAST_URL, params={
                'q': city,
                'appid': OPENWEATHERMAP_API_KEY,
                'units': 'metric'
            })
            forecast_data = forecast_response.json()

            # --- Process Forecast Data ---
            if forecast_data['cod'] == '200':
                
                # a. Hourly Forecast (Next 8 hours including "Now")
                hourly_list = forecast_data['list'][:8]
                hourly_forecast = []
                
                # Current time for "Now" label
                current_time = datetime.now()
                
                for i, item in enumerate(hourly_list):
                    forecast_dt = datetime.strptime(item['dt_txt'], '%Y-%m-%d %H:%M:%S')
                    
                    time_label = 'Now' if i == 0 else forecast_dt.strftime('%I %p').lstrip('0')

                    # If the first item is not the current hour, use current time
                    if i == 0 and forecast_dt.hour != current_time.hour:
                        time_label = 'Now'

                    hourly_forecast.append({
                        'time': time_label,
                        'temp': item['main']['temp'],
                        'description': item['weather'][0]['description'],
                        'icon': item['weather'][0].get('icon', '04d') # Use 04d as robust fallback
                    })

                # b. Daily Forecast (5 Days)
                daily_data = {}
                for item in forecast_data['list']:
                    date_str = item['dt_txt'].split(' ')[0]
                    day_name = day_from_dt(item['dt_txt'])
                    
                    if day_name not in daily_data:
                        # Initialize for a new day
                        daily_data[day_name] = {
                            'min_temp': item['main']['temp_max'], 
                            'max_temp': item['main']['temp_min'], 
                            'icon': '04d', # Default fallback icon
                            'dt_txt': item['dt_txt']
                        }
                    else:
                        # Update min/max temps
                        daily_data[day_name]['min_temp'] = min(daily_data[day_name]['min_temp'], item['main']['temp_min'])
                        daily_data[day_name]['max_temp'] = max(daily_data[day_name]['max_temp'], item['main']['temp_max'])

                        # Use the midday (12:00 or closest) icon for the daily summary
                        if '12:00:00' in item['dt_txt']:
                             daily_data[day_name]['icon'] = item['weather'][0].get('icon', '04d')
                
                # Convert dict to ordered list for 5 days
                daily_forecast = []
                today = datetime.now().strftime('%a')
                
                # Filter out 'Today' and get next 5 days
                sorted_days = list(daily_data.keys())
                
                # Find the index of today and start from the next day
                try:
                    start_index = sorted_days.index(today)
                except ValueError:
                    start_index = 0 # If today is not in the list for some reason
                    
                # Take the next 5 unique days
                # We need to ensure we don't display the current day as a 'daily' forecast (it's covered by Current Weather)
                count = 0
                for day_name in sorted_days:
                    if day_name != today and count < 5:
                        daily_forecast.append({
                            'day': day_name,
                            'max_temp': daily_data[day_name]['max_temp'],
                            'min_temp': daily_data[day_name]['min_temp'],
                            'icon': daily_data[day_name]['icon']
                        })
                        count += 1
                
                # If we don't get 5 full days (e.g., at end of API data), just show what we have
                daily_forecast = daily_forecast[:5]

        except requests.exceptions.RequestException as e:
            error = "Could not connect to the weather service."
            print(f"API Request Error: {e}")
        except Exception as e:
            error = "An unexpected error occurred."
            print(f"General Error: {e}")

    return render_template('index.html', 
                           weather=weather, 
                           city=city, 
                           error=error,
                           hourly_forecast=hourly_forecast,
                           daily_forecast=daily_forecast,
                           # NEW: Pass air quality data to the template
                           air_quality=air_quality)

if __name__ == '__main__':
    # Set a dummy API key if not set (for local testing without env var)
    if 'YOUR_API_KEY_HERE' in OPENWEATHERMAP_API_KEY:
        print("WARNING: Using a placeholder API key. Please replace 'YOUR_API_KEY_HERE' with a valid OpenWeatherMap API key in the app.py file.")
    app.run(debug=True)
