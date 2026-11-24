public class Demo
{
    void build(Map<String, Object> config)
    {
        SzRecord record = new SzRecord("CUSTOMERS", "REC-001", "NAME+DOB", null);
        Long result = ServiceUtilities.getConfigLong(config, "bigNumber", null, 100L);
        this.connectionTimeout = getConfigLong(config, TIMEOUT_KEY, 0L, DEFAULT_TIMEOUT);
        Task task = new Task("ACTION", new TreeMap<>(), new TreeSet<>(), group, true);
        Object entity = engine.getEntityByRecordId(theDataSourceCode, theRecordIdentifier, flags);
        assertEquals(AbstractSQLSchedulingService.CONNECTION_PROVIDER_KEY, providerKey);
        // A heavier continuation row is not lopsided: these stay P2.
        assertEquals(original, parsed, "Round-trip should work with negative values");
        RabbitMqUri rabbitUri = new RabbitMqUri(false, "user", "password", "localhost");
    }
}
