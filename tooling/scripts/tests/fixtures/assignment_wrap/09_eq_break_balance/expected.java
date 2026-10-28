public class Demo
{
    private File resourceDir;

    void run(Map<String, Object> config,
             Map<String, Object> record,
             String              resourcePath,
             Method              method)
    {
        Task task = new Task("ACTION", new TreeMap<>(),
                             new TreeSet<>(), group, true);
        CrossMatchKey keyDouble
            = new CrossMatchKey("TEST", "TEST", "NAME", "JOHN");
        Boolean result
            = ServiceUtilities.getConfigBoolean(config, "enabled", false);
        String recordSource
            = JsonUtilities.getString(record, "DATA_SOURCE_CODE");
        TemporaryDataCache tdc
            = new TemporaryDataCache(new ByteArrayInputStream(data));
        long diff
            = this.getLastBeginTime() - that.getLastBeginTime() - adjustment;
        Set<String> dataSources
            = (onlyLoaded) ? null : this.getConfiguredDataSources(true);
        this.resourceDir
            = (resourcePath != null) ? new File(resourcePath) : null;
        Instant instant
            = (Instant) method.invoke(null, sourceText, locatorValue, null);
    }

    void schedule(Task currentTask)
    {
        synchronized (this) {
            if (currentTask != null) {
                if (this.workerPool != null) {
                    Task<TaskResult> execTask = () -> {
                        return new TaskResult(currentTask, timers);
                    };
                    AsyncResult<TaskResult> result
                        = this.workerPool.execute(execTask);
                }
            }
        }
    }
}
