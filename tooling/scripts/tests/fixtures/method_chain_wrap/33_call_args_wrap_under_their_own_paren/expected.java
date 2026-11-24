public class Demo
{
    void firstCallWraps()
    {
        followUpScheduler.createTaskBuilder(REFRESH_ENTITY.toString(),
                                            someOtherBuilderArgument,
                                            andAnotherBuilderArg)
                         .resource(ENTITY_RESOURCE_KEY, followUpId)
                         .schedule(true);
    }

    void laterCallWraps()
    {
        this.foo = someService.chain1(a, b)
                              .chainMethod(veryLongArg1,
                                           veryLongArg2,
                                           veryLongArg3,
                                           veryLongArg4)
                              .chain3();
    }

    void unwrappedShapeWinsFirst()
    {
        corsDecorator = CorsService.builderForAnyOrigin()
            .allowRequestMethods(GET, HEAD, POST, PUT, DELETE, OPTIONS)
            .allowAllRequestHeaders(true)
            .newDecorator();
    }

    void blockBodyStaysWithTheStatement()
    {
        Runtime.getRuntime()
            .addShutdownHook(
                new Thread(() -> {
                    finalServer.destroy();
                }));
    }
}
