import boto3
from datetime import datetime, timedelta
from typing import Optional, Dict, List

class CloudTrailClient:
    
    def __init__(self, region: str = "us-east-1", profile: str = "infra-archaeology-mcp"):
        session = boto3.Session(profile_name=profile, region_name=region)
        self.client = session.client('cloudtrail')
        self.region = region
    
    def find_create_event(self, resouce_id: str, event_names: List[str], lookback_days: int = 90) -> Optional[Dict]:
        """
        Search CloudTrail for resource creation event
        
        Args:
            resource_id: The resource ID to search for
            event_names: List of CloudTrail event names to search (e.g., ['RunInstances'])
            lookback_days: How many days back to search
            
        Returns:
            Dictionary with creator info, or None if not found
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)
        
        try: 
            #Query to CloudTrail
            response = self.client.lookup_events(
                LookupAttributes = [
                    {
                        'AttributeKey': 'ResourceName',
                        'AttributeValue': resouce_id
                    }
                ],
                StartTime = start_time,
                EndTime = end_time,
                MaxResults=50
            )
            
            #Find the creation event
            for event in response.get('Events', []):
                if event['EventName'] in event_names:
                    return self._parse_event(event)
            
            if response.get('Events'):
                oldest_event = sorted(
                    response['Events'],
                    key=lambda x: x['EventTime']
                )[0]
                return self._parse_event(oldest_event)
            
            return None
        
        except Exception as e:
            print(f"CloudTrail query error: {e}")
            return None
    
    def _parse_event(self, event: Dict) -> Dict:
        return {
            "creator": event.get('Username', 'Unknown'),
            "created_at": event['EventTime'].isoformat(),
            "event_name": event['EventName'],
            "source_ip": event.get('SourceIPAddress', 'Unknown'),
            "user_agent": event.get('UserAgent', 'Unknown'),
            "event_id": event['EventId']
        }

EVENT_MAPPINGS = {
    "ec2": ["RunInstances", "CreateInstance"],
    "rds": ["CreateDBInstance", "CreateDBCluster"],
    "s3": ["CreateBucket"]
}