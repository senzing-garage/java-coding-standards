public class Demo
{
    void run()
    {
        try {
            // @start region="lookup"
            try {
                // 84 columns in the file, 72 in the rendered snippet,
                // which strips the region's 12-column indent: kept
                String result = engine.getEntity(entityId, SZ_ENTITY_DEFAULT_FLAGS);

                // wider than 80 even in the rendered snippet: wrapped
                JsonObject jsonObject = Json.createReader(new StringReader(result)).readObject();
            } catch (SzException e) {
                logError("Failed to get entity.", e);
            }
            // @end region="lookup"

            try {
                // outside the region the usual 80 columns apply
                String result = engine.getEntity(entityId, SZ_ENTITY_DEFAULT_FLAGS);
            } catch (SzException e) {
                logError("Failed to get entity.", e);
            }
        } catch (Exception e) {
            fail(e);
        }
    }
}
