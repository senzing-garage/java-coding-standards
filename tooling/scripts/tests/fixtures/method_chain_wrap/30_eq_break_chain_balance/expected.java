public class Demo
{
    void run(PooledConnection    pooledConn,
             Map<String, int[]>  deltaSumMap,
             String              compressedBase64Data)
    {
        long leaseTime = pooledConn.getCurrentLeaseHandler()
                                   .getLeaseTimeMillis();
        byte[] compressedData = Base64.getDecoder()
                                      .decode(compressedBase64Data);
        JsonObject settings = Json.createObjectBuilder()
                                  .add("TEST", "value")
                                  .build();
        SzRelatedEntity oldRelated
            = this.getOldRelatedEntities().get(myRelatedId);
        if (deltaSumMap != null) {
            if (parseException != null) {
                Iterator<Entry<String, int[]>> iter
                    = deltaSumMap.entrySet().iterator();
                this.errorLineNumber = parseException.getLocation()
                                                     .getLineNumber();
            }
        }
    }
}
