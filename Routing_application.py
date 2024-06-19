import json
import httpx
from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel
from typing import List, Dict
from pypolyline.cutil import decode_polyline
import requests

app = FastAPI()

class Location(BaseModel):
    lat: float
    lon: float

class RouteRequest(BaseModel):
    locations: List[Location]
    costing: str
    costing_options: dict
    units: str
    id: str

class RouteDetails(BaseModel):
    coordinates: List[List[float]]
    polyline: str

class RouteResponse(BaseModel):
    route_details: RouteDetails

@app.post("/get_incidents", response_model=List[Dict[str, float]])
async def get_incidents(
    min_lon: float, 
    min_lat: float, 
    max_lon: float, 
    max_lat: float
) -> List[Dict[str, float]]:
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    path_tomtom = (
        f"https://api.tomtom.com/traffic/services/5/incidentDetails"
        f"?key=JWGG704HAoF4HXgqW26nYR88fpa1DTgI"
        f"&bbox={bbox}"
        f"&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory}}}}}}"
        f"&language=en-GB&t=1111&timeValidityFilter=present"
    )
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(path_tomtom)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Request failed: {e}")

        response_data = resp.json() if resp.status_code == 200 else {}
        incidents_coordinates = []

        for incident in response_data.get('incidents', []):
            coordinates = incident['geometry']['coordinates']
            if isinstance(coordinates[0], list):
                for coord in coordinates:
                    incidents_coordinates.append({"lon": coord[0], "lat": coord[1]})
            else:
                incidents_coordinates.append({"lat": coordinates[1], "lon": coordinates[0]})

        return incidents_coordinates

async def get_route_details(route_request: RouteRequest, exclude_locations: List[Dict[str, float]], live_traffic: bool = True):
  
    data = route_request.model_dump() 
    data['exclude_locations'] = exclude_locations

    base_url = "http://localhost:8002/route"
    
    # print(base_url)
    # print(data)

    with open("payload_file.txt", "w") as file:
        json.dump(data, file, indent=4)
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(base_url, json=data)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Request failed: {e}")
        
        response_data = resp.json()
        # with open("response_file.txt", "w") as file:
        #     json.dump(response_data, file, indent=4)
        # print("===", response_data)

        if resp.status_code == 200:
            try:
                polyline_str = resp.json()['trip']['legs'][0]['shape']
                polyline_bytes = polyline_str.encode('latin-1')
                decoded_coords = decode_polyline(polyline_bytes, 6)
                decoded_coords_formatted = [[lon, lat] for lat, lon in decoded_coords]

                route_details = RouteDetails(coordinates=decoded_coords_formatted, polyline=polyline_str)
                return route_details
            except (KeyError, ValueError, UnicodeEncodeError) as e:
                raise HTTPException(status_code=500, detail=f"Error processing response: {e}")
        else:
            raise HTTPException(status_code=resp.status_code, detail=f"Request failed with status code {resp.status_code}. Response Content: {resp.text}")

@app.post("/combined", response_model=RouteResponse)
async def combined_handler(
    min_lon: float = Query(...),
    min_lat: float = Query(...),
    max_lon: float = Query(...),
    max_lat: float = Query(...),
    route_request: RouteRequest = Body(...),
    live_traffic: bool = Query(True)
):
    
    try:
        # print("1")
        exclude_locations = await get_incidents(min_lon, min_lat, max_lon, max_lat) if live_traffic else []
        # print(exclude_locations)
        # print("2")
        route_details = await get_route_details(route_request, exclude_locations, live_traffic)
        # print("3")
        return RouteResponse(route_details=route_details)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
