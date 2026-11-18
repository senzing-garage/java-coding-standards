public class Demo
{
    void run()
    {
        // @start region="register"
        long configId = configMgr.registerConfig(configDefinition, "Added CUSTOMERS data source");  // @highlight regex="configMgr.*"

        if (config == configMgr) throw new IllegalStateException("never happens");  // @replace regex="if.*" replacement="..."

        JsonObject jsonObj = Json.createReader(new StringReader(registry)).readObject();  // @highlight regex="registry"
        // @end region="register"
    }
}
