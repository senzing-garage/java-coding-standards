public class Demo
{
    void run()
    {
        // @start region="replace"
        for (int attempt = 0; attempt < MAXIMUM_REPLACE_ATTEMPTS_ALLOWED; attempt++) { // @highlight regex="attempt"
            try {
                configMgr.replaceDefaultConfigId(currentDefaultConfigId, newConfigId);
                break;
            } catch (SzReplaceConflictException | SzNotFoundException exception) { // @highlight regex="SzReplaceConflictException"
                // not tagged, so this still wraps
                logWarning("Configuration changed concurrently; retrying the replacement.", exception);
            }
        }
        // @end region="replace"
    }
}
